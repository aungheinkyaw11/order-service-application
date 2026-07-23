import asyncio
import json
from typing import Any

import nats
from nats.aio.client import Client as NATS
from nats.js.api import StorageType, StreamConfig


class OrderPublisher:
    def __init__(
        self, servers: list[str], stream: str, subject: str, connect_timeout: float = 5.0
    ) -> None:
        self.servers = servers
        self.stream = stream
        self.subject = subject
        self.connect_timeout = connect_timeout
        self.client: NATS | None = None
        self.jetstream: Any = None
        self._connect_lock = asyncio.Lock()

    async def connect(self) -> None:
        if self.jetstream is not None:
            return
        async with self._connect_lock:
            if self.jetstream is not None:
                return
            client = await nats.connect(
                self.servers,
                name="orders-api",
                connect_timeout=self.connect_timeout,
                drain_timeout=self.connect_timeout,
            )
            try:
                jetstream = client.jetstream()
                await ensure_stream(jetstream, self.stream, self.subject)
            except Exception:
                await client.close()
                raise
            self.client = client
            self.jetstream = jetstream

    async def close(self) -> None:
        if self.client is not None:
            await self.client.drain()
            self.client = None
            self.jetstream = None

    async def publish(self, payload: dict[str, Any]) -> None:
        if self.jetstream is None:
            await self.connect()
        if self.jetstream is None:
            raise RuntimeError("NATS connection failed")
        await self.jetstream.publish(
            self.subject,
            json.dumps(payload, separators=(",", ":"), default=str).encode(),
            timeout=self.connect_timeout,
        )


async def ensure_stream(jetstream: Any, stream: str, subject: str) -> None:
    try:
        info = await jetstream.stream_info(stream)
        if subject not in info.config.subjects:
            subjects = [*info.config.subjects, subject]
            await jetstream.update_stream(config=StreamConfig(name=stream, subjects=subjects))
    except nats.js.errors.NotFoundError:
        await jetstream.add_stream(
            config=StreamConfig(
                name=stream,
                subjects=[subject],
                storage=StorageType.FILE,
            )
        )
