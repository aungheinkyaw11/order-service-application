#!/usr/bin/env bash
set -Eeuo pipefail

environment="${1:-}"
aws_profile="${2:-}"

if [[ "${environment}" != "dev" && "${environment}" != "prod" ]]; then
  echo "Usage: $0 <dev|prod> [aws-profile]" >&2
  exit 1
fi

region="${AWS_REGION:-us-east-1}"
prefix="order-service-${environment}"
cluster="${prefix}-cluster"
api_service="${prefix}-api"
migration_task="${prefix}-migration"

aws_args=(--region "${region}")
if [[ -n "${aws_profile}" ]]; then
  aws_args+=(--profile "${aws_profile}")
fi

network_configuration="$(aws ecs describe-services \
  "${aws_args[@]}" \
  --cluster "${cluster}" \
  --services "${api_service}" \
  --query 'services[0].networkConfiguration' \
  --output json)"

task_arn="$(aws ecs run-task \
  "${aws_args[@]}" \
  --cluster "${cluster}" \
  --task-definition "${migration_task}" \
  --launch-type FARGATE \
  --network-configuration "${network_configuration}" \
  --query 'tasks[0].taskArn' \
  --output text)"

if [[ -z "${task_arn}" || "${task_arn}" == "None" ]]; then
  echo "Migration task did not start." >&2
  exit 1
fi

echo "Migration started: ${task_arn}"
echo "Waiting for it to finish..."

aws ecs wait tasks-stopped \
  "${aws_args[@]}" \
  --cluster "${cluster}" \
  --tasks "${task_arn}"

exit_code="$(aws ecs describe-tasks \
  "${aws_args[@]}" \
  --cluster "${cluster}" \
  --tasks "${task_arn}" \
  --query 'tasks[0].containers[0].exitCode' \
  --output text)"

if [[ "${exit_code}" != "0" ]]; then
  echo "Migration failed with exit code ${exit_code}." >&2
  aws ecs describe-tasks \
    "${aws_args[@]}" \
    --cluster "${cluster}" \
    --tasks "${task_arn}" \
    --query 'tasks[0].{stoppedReason:stoppedReason,containers:containers[].{name:name,exitCode:exitCode,reason:reason}}' \
    --output json >&2
  exit 1
fi

echo "Migration completed successfully."
