import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg


class Database:
    def __init__(
        self,
        url: str,
        connect_timeout: float = 5.0,
        command_timeout: float = 10.0,
    ) -> None:
        self.url = url
        self.connect_timeout = connect_timeout
        self.command_timeout = command_timeout
        self.pool: asyncpg.Pool | None = None
        self._connect_lock = asyncio.Lock()

    async def connect(self) -> None:
        if self.pool is not None:
            return
        async with self._connect_lock:
            if self.pool is None:
                self.pool = await asyncpg.create_pool(
                    self.url,
                    min_size=1,
                    max_size=10,
                    timeout=self.connect_timeout,
                    command_timeout=self.command_timeout,
                )

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    async def _pool(self) -> asyncpg.Pool:
        if self.pool is None:
            await self.connect()
        if self.pool is None:
            raise RuntimeError("database connection failed")
        return self.pool

    async def check(self) -> None:
        pool = await self._pool()
        await pool.fetchval("SELECT 1")

    async def create_order(self, order_id: UUID, symbol: str, quantity: int) -> Mapping[str, Any]:
        pool = await self._pool()
        row = await pool.fetchrow(
            """
            INSERT INTO orders (id, symbol, quantity, status)
            VALUES ($1, $2, $3, 'pending')
            RETURNING id, symbol, quantity, status, created_at, updated_at
            """,
            order_id,
            symbol,
            quantity,
        )
        if row is None:
            raise RuntimeError("order insert returned no row")
        return dict(row)

    async def get_order(self, order_id: UUID) -> Mapping[str, Any] | None:
        pool = await self._pool()
        row = await pool.fetchrow(
            """
            SELECT id, symbol, quantity, status, created_at, updated_at
            FROM orders
            WHERE id = $1
            """,
            order_id,
        )
        return dict(row) if row else None

    async def fill_order(self, order_id: UUID) -> bool:
        pool = await self._pool()
        result = await pool.execute(
            """
            UPDATE orders
            SET status = 'filled', updated_at = NOW()
            WHERE id = $1 AND status = 'pending'
            """,
            order_id,
        )
        return result == "UPDATE 1"


async def run_migrations(
    database_url: str,
    migrations_dir: Path,
    connect_timeout: float = 5.0,
    command_timeout: float = 10.0,
) -> None:
    connection = await asyncpg.connect(
        database_url,
        timeout=connect_timeout,
        command_timeout=command_timeout,
    )
    try:
        await connection.execute("SELECT pg_advisory_lock(728194263)")
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        for migration in sorted(migrations_dir.glob("*.sql")):
            applied = await connection.fetchval(
                "SELECT 1 FROM schema_migrations WHERE version = $1", migration.name
            )
            if applied:
                continue
            async with connection.transaction():
                await connection.execute(migration.read_text(encoding="utf-8"))
                await connection.execute(
                    "INSERT INTO schema_migrations (version) VALUES ($1)", migration.name
                )
    finally:
        await connection.close()
