# Trading Order Service

This is a minimal FastAPI order API backed by PostgreSQL and NATS JetStream. 
A worker consumes messages and changes orders from `pending` to `filled` after two seconds.

```text
POST /orders -> PostgreSQL (pending) -> NATS JetStream -> worker -> PostgreSQL (filled)
```
---
## Component guide

- `app/api.py` owns the HTTP endpoints, request IDs, and dependency lifecycle.
- `app/worker.py` consumes the durable JetStream subscription and fills orders.
- `app/database.py` contains the connection pool, queries, and migration runner.
- `app/messaging.py` creates the stream and publishes order messages.
- `app/logging.py` emits one-line JSON logs for CloudWatch-compatible ingestion.
- `compose.yaml` runs PostgreSQL, NATS, migrations, the API, and the worker locally.

---
## Run locally
To run in your local, please follow this [link](docs/run_locally.md)

---
## Delivery branches

We have two main branches: `development` and `main`.
The `main` branch represents the **production environment**. 

When code is merged into `main`, linting and tests run automatically, but production is not deployed automatically.
The production deployment must be started **manually and requires human approval**.

When a pull request is opened in the `development` branch, the pipeline runs linting and tests only. 
After the pull request is merged into `development`, the pipeline runs the tests, builds and pushes the Docker image, and deploys it to the **development ECS cluster**.

The CI/CD pipeline does not run when code is only pushed to a `feature` branch. Developers test their code locally on the `feature branch`. Automated linting and tests run after they open a pull request to `development`.

```
feature branch
    │
    ├── push only
    │     No workflow: feature pushes are not configured
    │
    └── Pull Request → development
          Lint and test only
                 │
                 ▼
          Merge into development
                 │
                 ├── Lint and test
                 ├── Build Docker image
                 ├── Push image to dev ECR
                 └── Deploy API and worker to dev ECS

development → Pull Request → main
          Lint and test only
                 │
                 ▼
          Merge into main
                 │
                 └── Lint and test only

Manual workflow on main
    │
    ├── Lint and test
    ├── Wait for production approval
    ├── Build and push production image
    └── Deploy to production ECS
```

```text
feature/*  -> pull request -> development -> automatic dev deployment
development -> pull request -> main      -> approval -> production deployment
```

Configure these non-secret repository variables under GitHub **Settings > Secrets and variables >
Actions > Variables**:

| Variable | Example value |
| --- | --- |
| `AWS_ACCOUNT_ID` | `499193102935` |
| `ECR_REPOSITORY_DEV` | `order-service-dev` |
| `ECR_REPOSITORY_PROD` | `order-service-prod` |
| `ECS_CLUSTER_DEV` | `order-service-dev-cluster` |
| `API_SERVICE_DEV` | `order-service-dev-api` |
| `WORKER_SERVICE_DEV` | `order-service-dev-worker` |
| `ECS_CLUSTER_PROD` | `order-service-prod-cluster` |
| `API_SERVICE_PROD` | `order-service-prod-api` |
| `WORKER_SERVICE_PROD` | `order-service-prod-worker` |
| `AWS_DEV_ROLE_ARN` | `arn:aws:iam::499193102935:role/order-service-dev-github-actions` |
| `AWS_PROD_ROLE_ARN` | `arn:aws:iam::499193102935:role/order-service-prod-github-actions` |

---
## Application processes and endpoints

The project uses one Docker image for three separate processes. Each process uses a different
Python module command:

| Process   | Command                        | Purpose                                                                                |
| --------- | ------------------------------ | -------------------------------------------------------------------------------------- |
| Migration | `python -m app.migrate`        | Applies unapplied SQL files from the `migrations/` directory to PostgreSQL.            |
| API       | `python -m app.api_entrypoint` | Starts Uvicorn and serves the FastAPI application from `app.api:app` on port `8000`.   |
| Worker    | `python -m app.worker`         | Consumes order messages from NATS JetStream and updates PostgreSQL orders to `filled`. |

---
