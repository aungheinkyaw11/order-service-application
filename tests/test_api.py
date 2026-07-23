from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app import api
from tests.conftest import FakeDatabase, FakePublisher


async def test_health_starts_without_connecting_to_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnavailableDatabase:
        async def connect(self) -> None:
            raise ConnectionError("database unavailable")

        async def close(self) -> None:
            pass

    class UnavailablePublisher:
        async def connect(self) -> None:
            raise ConnectionError("NATS unavailable")

        async def close(self) -> None:
            pass

    monkeypatch.setattr(api, "Database", lambda *_: UnavailableDatabase())
    monkeypatch.setattr(api, "OrderPublisher", lambda *_: UnavailablePublisher())
    isolated_app = FastAPI(lifespan=api.lifespan)
    isolated_app.add_api_route("/health", api.health)

    async with isolated_app.router.lifespan_context(isolated_app):
        async with AsyncClient(
            transport=ASGITransport(app=isolated_app), base_url="http://test"
        ) as test_client:
            response = await test_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_is_liveness_only(client: AsyncClient, database: FakeDatabase) -> None:
    database.available = False

    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert UUID(response.headers["X-Request-ID"])


async def test_ready_when_database_is_available(client: AsyncClient) -> None:
    response = await client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


async def test_ready_when_database_is_unavailable(
    client: AsyncClient, database: FakeDatabase
) -> None:
    database.available = False

    response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "database unavailable"}


async def test_create_order_validates_input(client: AsyncClient) -> None:
    blank = await client.post("/orders", json={"symbol": "  ", "quantity": 1})
    zero = await client.post("/orders", json={"symbol": "AAPL", "quantity": 0})
    boolean = await client.post("/orders", json={"symbol": "AAPL", "quantity": True})

    assert blank.status_code == 422
    assert zero.status_code == 422
    assert boolean.status_code == 422


async def test_create_and_retrieve_order_with_request_id(
    client: AsyncClient, publisher: FakePublisher
) -> None:
    request_id = str(uuid4())

    created = await client.post(
        "/orders",
        json={"symbol": "AAPL", "quantity": 5},
        headers={"X-Request-ID": request_id},
    )

    assert created.status_code == 201
    assert created.headers["X-Request-ID"] == request_id
    assert created.json()["status"] == "pending"
    order_id = created.json()["id"]
    assert publisher.messages == [
        {
            "order_id": order_id,
            "symbol": "AAPL",
            "quantity": 5,
            "request_id": request_id,
        }
    ]

    retrieved = await client.get(f"/orders/{order_id}")
    assert retrieved.status_code == 200
    assert retrieved.json()["id"] == order_id
    assert retrieved.json()["symbol"] == "AAPL"
    assert retrieved.json()["quantity"] == 5
    assert retrieved.json()["status"] == "pending"


async def test_invalid_request_id_is_replaced(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "not-a-uuid"})

    assert response.headers["X-Request-ID"] != "not-a-uuid"
    assert UUID(response.headers["X-Request-ID"])


async def test_missing_order_returns_404(client: AsyncClient) -> None:
    response = await client.get(f"/orders/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "order not found"}


async def test_dependency_failure_returns_sanitized_json(
    client: AsyncClient, publisher: FakePublisher
) -> None:
    async def fail_publish(_: object) -> None:
        raise ConnectionError("nats://user:secret@nats.internal:4222 is unavailable")

    publisher.publish = fail_publish  # type: ignore[method-assign]

    response = await client.post("/orders", json={"symbol": "AAPL", "quantity": 5})

    assert response.status_code == 500
    assert response.json() == {"detail": "internal server error"}
    assert "secret" not in response.text
