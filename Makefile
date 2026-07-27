.PHONY: start stop test integration-test lint format logs smoke-test

start:
	docker compose up --build --detach --wait

stop:
	docker compose down

test:
	docker build --target development --tag order-service-test .
	docker run --rm --volume "$(CURDIR):/src" --workdir /src order-service-test pytest

integration-test:
	docker compose --profile test run --rm --build integration-test

lint:
	docker build --target development --tag order-service-test .
	docker run --rm --volume "$(CURDIR):/src" --workdir /src order-service-test ruff check .

format:
	docker build --target development --tag order-service-test .
	docker run --rm --volume "$(CURDIR):/src" --workdir /src order-service-test ruff format .

logs:
	docker compose logs --follow api worker

smoke-test:
	./scripts/smoke_test.sh