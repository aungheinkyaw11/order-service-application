# Trading Order Service

This is a minimal FastAPI order API backed by PostgreSQL and NATS JetStream. A separate
worker consumes durable messages and changes orders from `pending` to `filled` after two seconds.

```text
POST /orders -> PostgreSQL (pending) -> NATS JetStream -> worker -> PostgreSQL (filled)
```

## Component guide

- `app/api.py` owns the HTTP endpoints, request IDs, and dependency lifecycle.
- `app/worker.py` consumes the durable JetStream subscription and fills orders.
- `app/database.py` contains the connection pool, queries, and migration runner.
- `app/messaging.py` creates the stream and publishes order messages.
- `app/logging.py` emits one-line JSON logs for CloudWatch-compatible ingestion.
- `compose.yaml` runs PostgreSQL, NATS, migrations, the API, and the worker locally.

## Prerequisites

- Docker with Docker Compose
- `make`, `curl`, and Python 3 (only used by the smoke-test script for JSON parsing)

No host Python environment is required. The application and test images use Python 3.12.

## Run locally

```sh
cp .env.example .env
make start
docker compose ps
make smoke-test
```

The API listens on <http://localhost:8000>. Follow correlated JSON application logs with:

```sh
make logs
```

Stop containers with `make stop`. To also delete local PostgreSQL and JetStream data, run
`docker compose down --volumes` explicitly.

Expected smoke-test behavior is an initial `pending` order followed by `filled` after roughly two
seconds. Its final section prints API and worker log lines sharing the same request ID.

## API

```sh
curl -i http://localhost:8000/health
curl -i http://localhost:8000/ready
curl -i -X POST http://localhost:8000/orders \
  -H 'Content-Type: application/json' \
  -H 'X-Request-ID: 48af2fc4-5042-4f01-ad5b-e4f6f51a56c9' \
  -d '{"symbol":"AAPL","quantity":5}'
curl -i http://localhost:8000/orders/ORDER_ID
```

`X-Request-ID` must be a UUID. The API preserves a valid value or creates a new UUID, returns it
in the response, publishes it in the JetStream message, and includes it in API and worker logs.

## Development checks

```sh
make test
make integration-test
make lint
make format
```

Run an existing ECS migration task manually without exporting resource names:

```sh
./scripts/run_migration.sh dev aunghein
./scripts/run_migration.sh prod aunghein
```

The first argument selects the environment. The optional second argument is the local AWS CLI
profile; omit it when the default AWS credentials are already configured.

## Delivery branches

Feature branches are merged into `development` through a pull request. Pull requests run linting and
tests but do not publish an image or deploy. A push to `development` publishes the full Git commit SHA
to the development ECR repository and automatically deploys the dev ECS services.

Production changes move from `development` to `main` through a reviewed pull request. A push to `main`
runs the tests and then pauses at the protected GitHub `prod` environment. After a required reviewer
approves the job, GitHub assumes the production OIDC role, publishes the exact commit image to the
production ECR repository, runs the migration, and deploys the production worker and API services.

```text
feature/*  -> pull request -> development -> automatic dev deployment
development -> pull request -> main      -> approval -> production deployment
```

Configure repository variables `AWS_DEV_ROLE_ARN` and `AWS_PROD_ROLE_ARN`. Create a GitHub
environment named `prod` and add a required reviewer. Protect `main` so changes require an approved
pull request and passing CI checks.

ECS uses rolling deployments and the Terraform-managed deployment circuit breaker. If new tasks
cannot become healthy, ECS rolls back to the last successful revision and the workflow fails. The
deployment script is `scripts/deploy_ecs.sh`; resource names are visible in the workflow, while AWS
access uses the environment-specific GitHub role variables and OIDC instead of stored AWS keys.

Dependencies are fully pinned in `requirements.txt` and `requirements-dev.txt`. The SQL migration
runner records applied files in `schema_migrations`; Compose completes migrations before starting
the API and worker.

`make test` runs isolated API and worker unit tests. The real integration test is skipped there and
is enabled only by `make integration-test`; that command starts the Compose dependencies and proves
the complete HTTP, PostgreSQL, JetStream, and worker flow. This separation keeps the fast test suite
suitable for every commit and gives CI an explicit service-level gate.

## Runtime configuration

All runtime configuration is supplied through environment variables. For local development,
Compose loads them from the ignored `.env` file; `.env.example` is the safe committed template.
AWS will inject the same variables from task configuration and a secrets service instead of using a
file. Important settings are:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | local Compose URL | PostgreSQL connection string |
| `NATS_URL` | `nats://nats:4222` | NATS server address |
| `PROCESSING_DELAY_SECONDS` | `2` | simulated fill delay |
| `DEPENDENCY_CONNECT_TIMEOUT_SECONDS` | `5` | bounded dependency connection time |
| `DEPENDENCY_COMMAND_TIMEOUT_SECONDS` | `10` | bounded PostgreSQL command time |
| `SHUTDOWN_TIMEOUT_SECONDS` | `10` | maximum graceful drain/close time |
| `IMAGE_VERSION` | `local` | build-time commit or image identifier logged at startup; do not put it in `.env` |

For a release image, pass the commit SHA without putting environment configuration in the image:

```sh
docker build --build-arg IMAGE_VERSION="$(git rev-parse HEAD)" -t order-service:release .
```

The runtime container uses UID/GID `10001`, contains no shell-time credentials, and uses one image
with different commands for migration, API, and worker tasks. Dependency failures return a generic
JSON `500` response; connection details remain in restricted application logs rather than responses.

## Processing guarantees

The JetStream consumer is durable and uses explicit acknowledgements. The worker acknowledges only
after a successful database operation. Its conditional `pending` to `filled` update makes repeated
delivery safe. A malformed message is negatively acknowledged and retried; a message for an order
that does not exist is terminated because retrying cannot repair it.

The database insert and JetStream publish are separate operations. If publishing fails after the
insert commits, the API returns an error but leaves a pending order. A production milestone should
use a transactional outbox and relay to close that dual-write gap.

## Interview walkthrough notes

- `/health` is liveness only, so a database outage does not cause an ECS restart loop.
- `/ready` executes `SELECT 1`; a load balancer can stop routing while PostgreSQL is unavailable.
- The request ID is accepted or generated by the API, placed in the NATS payload, and restored into
  worker logging context.
- Explicit acknowledgement plus the conditional status update provides at-least-once delivery with
  idempotent processing for this two-state workflow.
- API and worker drain NATS and close PostgreSQL connections during shutdown, with bounded timeouts
  so an ECS replacement cannot wait forever.
- The accepted weakness is the database/NATS dual write. The prioritized production improvement is
  a transactional outbox, but it is intentionally omitted because the task evaluates the platform.

## Application milestone checklist

1. Run `make start` and inspect `docker compose ps` until services are healthy.
2. Run `make smoke-test` and identify the correlated API and worker log events.
3. Run `make lint`, `make test`, and `make integration-test`.
4. Run `docker image inspect order-service:local --format '{{.Config.User}}'` and expect `app`.
5. Be ready to explain acknowledgement, duplicate delivery, readiness, and the dual-write tradeoff.

## Scope

This milestone intentionally contains no Terraform, AWS resources, GitHub Actions, or production
deployment configuration. Those are the next platform milestone and should consume this immutable
application image without changing its public API.
