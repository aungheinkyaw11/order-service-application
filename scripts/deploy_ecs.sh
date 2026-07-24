#!/usr/bin/env bash
set -Eeuo pipefail

required=(AWS_REGION IMAGE_URI ECS_CLUSTER API_SERVICE WORKER_SERVICE MIGRATION_TASK_FAMILY) # check required values
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
            if .name == $container then .image = $image else . end
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

current_api_task="$(jq -r --arg service "${API_SERVICE}" '.services[] | select(.serviceName == $service) | .taskDefinition' <<<"${service_details}")"
current_worker_task="$(jq -r --arg service "${WORKER_SERVICE}" '.services[] | select(.serviceName == $service) | .taskDefinition' <<<"${service_details}")"
api_network="$(jq -c --arg service "${API_SERVICE}" '.services[] | select(.serviceName == $service) | .networkConfiguration' <<<"${service_details}")"

api_task="$(register_with_image "${current_api_task}" api)"
worker_task="$(register_with_image "${current_worker_task}" worker)"
migration_task="$(register_with_image "${MIGRATION_TASK_FAMILY}" migration)"

echo "Registered API task: ${api_task}"
echo "Registered worker task: ${worker_task}"
echo "Registered migration task: ${migration_task}"

# run the migration first
migration_result="$(aws ecs run-task \
  --cluster "${ECS_CLUSTER}" \
  --task-definition "${migration_task}" \
  --launch-type FARGATE \
  --network-configuration "${api_network}")"

if [[ "$(jq '.failures | length' <<<"${migration_result}")" -ne 0 ]]; then
  jq '.failures' <<<"${migration_result}" >&2
  exit 1
fi

migration_arn="$(jq -r '.tasks[0].taskArn' <<<"${migration_result}")"
echo "Waiting for migration task: ${migration_arn}"
aws ecs wait tasks-stopped --cluster "${ECS_CLUSTER}" --tasks "${migration_arn}"

migration_description="$(aws ecs describe-tasks --cluster "${ECS_CLUSTER}" --tasks "${migration_arn}")"
migration_exit="$(jq -r '.tasks[0].containers[0].exitCode // -1' <<<"${migration_description}")"
if [[ "${migration_exit}" != "0" ]]; then
  jq '.tasks[0] | {stoppedReason, containers: [.containers[] | {name, exitCode, reason}]}' <<<"${migration_description}" >&2
  exit 1
fi

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
    echo "### ECS development deployment"
    echo "- Image: \`${IMAGE_URI}\`"
    echo "- API task: \`${api_task}\`"
    echo "- Worker task: \`${worker_task}\`"
    echo "- Migration task: \`${migration_task}\` (exit 0)"
  } >>"${GITHUB_STEP_SUMMARY}"
fi