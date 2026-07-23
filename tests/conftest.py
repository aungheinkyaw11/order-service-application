from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import app


class FakeDatabase:
    def __init__(self) -> None:
        self.available = True
        self.orders: dict[UUID, dict[str, Any]] = {}

    async def check(self) -> None:
        if not self.available:
            raise ConnectionError("database unavailable")

    async def create_order(self, order_id: UUID, symbol: str, quantity: int) -> dict[str, Any]:
        now = datetime.now(UTC)
        order = {
            "id": order_id,
            "symbol": symbol,
            "quantity": quantity,
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        }
        self.orders[order_id] = order
        return order

    async def get_order(self, order_id: UUID) -> dict[str, Any] | None:
        return self.orders.get(order_id)


class FakePublisher:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def publish(self, payload: dict[str, Any]) -> None:
        self.messages.append(payload)


@pytest.fixture
def database() -> FakeDatabase:
    return FakeDatabase()


@pytest.fixture
def publisher() -> FakePublisher:
    return FakePublisher()


@pytest.fixture
async def client(database: FakeDatabase, publisher: FakePublisher) -> AsyncIterator[AsyncClient]:
    @asynccontextmanager
    async def test_lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield

    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = test_lifespan
    app.state.database = database
    app.state.publisher = publisher
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as test_client:
            yield test_client
    finally:
        app.router.lifespan_context = original_lifespan
