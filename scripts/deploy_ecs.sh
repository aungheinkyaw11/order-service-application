#!/usr/bin/env bash
set -Eeuo pipefail

required=(AWS_REGION IMAGE_URI ECS_CLUSTER API_SERVICE WORKER_SERVICE) # check required values
for name in "${required[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    echo "Missing required environment variable: ${name}" >&2
    exit 1
  fi
done
command -v aws >/dev/null # AWS CLI and jq exist
command -v jq >/dev/null

deploy_tmp="$(mktemp -d)" # temporary directory
trap 'rm -rf "${deploy_tmp}"' EXIT  # script finishes, trap deletes only that temporary directory

# create a new task-definition revision
register_with_image() {
  local source_task="$1"
  local container_name="$2"
  local output_file="${deploy_tmp}/${container_name}.json"

  aws ecs describe-task-definition --task-definition "${source_task}" --include TAGS |
    jq --arg image "${IMAGE_URI}" --arg container "${container_name}" '
      (.taskDefinition
        | del(
            .taskDefinitionArn,
            .revision,
            .status,
            .requiresAttributes,
            .compatibilities,
            .registeredAt,
            .registeredBy,
            .deregisteredAt
          )
        | .containerDefinitions |= map(
            if (.name == $container or .name == "migration") then .image = $image else . end
          )) as $definition
      | $definition + {tags: (.tags // [])}
    ' >"${output_file}"

  aws ecs register-task-definition \
    --cli-input-json "file://${output_file}" \
    --query 'taskDefinition.taskDefinitionArn' \
    --output text
}

# read the current services
service_details="$(aws ecs describe-services \
  --cluster "${ECS_CLUSTER}" \
  --services "${API_SERVICE}" "${WORKER_SERVICE}")"

if [[ "$(jq '.failures | length' <<<"${service_details}")" -ne 0 ]]; then
  jq '.failures' <<<"${service_details}" >&2
  exit 1
fi

# Use the latest active revision in each task family. Terraform can add structural changes,
# such as the migration init container, while this script replaces its image and deploys it.
api_task_family="$(jq -r --arg service "${API_SERVICE}" '.services[] | select(.serviceName == $service) | .taskDefinition | split("/")[-1] | split(":")[0]' <<<"${service_details}")"
worker_task_family="$(jq -r --arg service "${WORKER_SERVICE}" '.services[] | select(.serviceName == $service) | .taskDefinition | split("/")[-1] | split(":")[0]' <<<"${service_details}")"

api_task="$(register_with_image "${api_task_family}" api)"
worker_task="$(register_with_image "${worker_task_family}" worker)"

echo "Registered API task: ${api_task}"
echo "Registered worker task: ${worker_task}"

# update both ECS services
aws ecs update-service --cluster "${ECS_CLUSTER}" --service "${WORKER_SERVICE}" --task-definition "${worker_task}" >/dev/null
aws ecs update-service --cluster "${ECS_CLUSTER}" --service "${API_SERVICE}" --task-definition "${api_task}" >/dev/null

# wait for healthy services
if ! aws ecs wait services-stable --cluster "${ECS_CLUSTER}" --services "${API_SERVICE}" "${WORKER_SERVICE}"; then
  aws ecs describe-services \
    --cluster "${ECS_CLUSTER}" \
    --services "${API_SERVICE}" "${WORKER_SERVICE}" \
    --query 'services[].{service:serviceName,deployments:deployments,events:events[0:10]}' >&2
  exit 1
fi

# verify what is actually running
verify_running_task() {
  local service="$1"
  local expected_task="$2"
  local task_arns
  local running_defs

  task_arns="$(aws ecs list-tasks --cluster "${ECS_CLUSTER}" --service-name "${service}" --desired-status RUNNING --query 'taskArns' --output json)"
  if [[ "$(jq 'length' <<<"${task_arns}")" -eq 0 ]]; then
    echo "No running tasks found for ${service}" >&2
    return 1
  fi
  running_defs="$(aws ecs describe-tasks --cluster "${ECS_CLUSTER}" --tasks $(jq -r '.[]' <<<"${task_arns}") --query 'tasks[].taskDefinitionArn' --output json)"
  if [[ "$(jq --arg expected "${expected_task}" 'all(.[]; . == $expected)' <<<"${running_defs}")" != "true" ]]; then
    echo "${service} is not running only ${expected_task}; ECS may have rolled back" >&2
    jq . <<<"${running_defs}" >&2
    return 1
  fi
}

# deployment summary
verify_running_task "${API_SERVICE}" "${api_task}"
verify_running_task "${WORKER_SERVICE}" "${worker_task}"

echo "Deployment complete: ${IMAGE_URI}"
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    echo "### ECS ${DEPLOY_ENV:-unknown} deployment"
    echo "- Image: \`${IMAGE_URI}\`"
    echo "- API task: \`${api_task}\`"
    echo "- Worker task: \`${worker_task}\`"
  } >>"${GITHUB_STEP_SUMMARY}"
fi
