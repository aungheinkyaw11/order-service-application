import asyncio
import os
from uuid import uuid4

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1",
    reason="set RUN_INTEGRATION=1 inside the Compose test environment",
)


async def test_real_postgres_nats_and_worker_flow() -> None:
    base_url = os.environ.get("API_URL", "http://api:8000")
    request_id = str(uuid4())

    async with httpx.AsyncClient(base_url=base_url, timeout=5) as client:
        health = await client.get("/health")
        readiness = await client.get("/ready")
        created = await client.post(
            "/orders",
            json={"symbol": "AAPL", "quantity": 5},
            headers={"X-Request-ID": request_id},
        )

        assert health.status_code == 200
        assert readiness.status_code == 200
        assert created.status_code == 201
        assert created.headers["X-Request-ID"] == request_id
        assert created.json()["status"] == "pending"

        order_id = created.json()["id"]
        deadline = asyncio.get_running_loop().time() + 10
        while True:
            order = await client.get(f"/orders/{order_id}")
            assert order.status_code == 200
            if order.json()["status"] == "filled":
                break
            if asyncio.get_running_loop().time() >= deadline:
                raise AssertionError("worker did not fill the order within 10 seconds")
            await asyncio.sleep(0.25)
