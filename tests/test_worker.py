import json
from typing import Any
from uuid import uuid4

from app.worker import handle_message, process_message


class FakeMessage:
    def __init__(self, payload: dict[str, Any] | bytes) -> None:
        self.data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.acked = False
        self.nacked = False
        self.terminated = False

    async def ack(self) -> None:
        self.acked = True

    async def nak(self) -> None:
        self.nacked = True

    async def term(self) -> None:
        self.terminated = True


class FakeWorkerDatabase:
    def __init__(self, status: str | None = "pending") -> None:
        self.status = status
        self.fill_calls = 0
        self.fail_on_get = False

    async def get_order(self, _: object) -> dict[str, str] | None:
        if self.fail_on_get:
            raise ConnectionError("database unavailable")
        return {"status": self.status} if self.status is not None else None

    async def fill_order(self, _: object) -> bool:
        self.fill_calls += 1
        self.status = "filled"
        return True


def order_message() -> FakeMessage:
    return FakeMessage({"order_id": str(uuid4()), "request_id": str(uuid4())})


async def test_worker_fills_and_acknowledges_pending_order() -> None:
    database = FakeWorkerDatabase()
    message = order_message()

    await process_message(message, database, delay=0)

    assert database.fill_calls == 1
    assert message.acked is True
    assert message.nacked is False


async def test_worker_acknowledges_duplicate_without_filling_again() -> None:
    database = FakeWorkerDatabase(status="filled")
    message = order_message()

    await process_message(message, database, delay=0)

    assert database.fill_calls == 0
    assert message.acked is True


async def test_worker_terminates_message_for_missing_order() -> None:
    database = FakeWorkerDatabase(status=None)
    message = order_message()

    await process_message(message, database, delay=0)

    assert message.terminated is True
    assert message.acked is False
    assert message.nacked is False


async def test_worker_negatively_acknowledges_malformed_message() -> None:
    database = FakeWorkerDatabase()
    message = FakeMessage(b"not-json")

    await handle_message(message, database, delay=0)

    assert message.nacked is True
    assert message.acked is False


async def test_worker_negatively_acknowledges_database_failure() -> None:
    database = FakeWorkerDatabase()
    database.fail_on_get = True
    message = order_message()

    await handle_message(message, database, delay=0)

    assert message.nacked is True
    assert message.acked is False
