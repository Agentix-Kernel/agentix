"""PostgreSQL relational driver — asyncpg transport.

Implements the kernel's :class:`RelationalDriver` protocol over an asyncpg
connection pool. Use ``agentix[postgresql]`` to install the ``asyncpg``
dependency.

Note: the kernel's DDL is written in the SQLite dialect (WAL, FTS5,
``PRAGMA table_info``). This driver satisfies the protocol, but the kernel
store's schema does not port automatically — dialect adaptation is app work,
documented in ``docs/drivers.md``.

Error classification: connectivity and lock-timeout → ``DriverUnavailable``
(retryable); constraint violations, malformed SQL → ``DriverInvalidRequest``.
"""

from __future__ import annotations

import os
from typing import Any

import structlog

from agentix.config import DriverSpec
from agentix.drivers.base import (
    DriverDescriptor,
    DriverInvalidRequest,
    DriverUnavailable,
)
from agentix.drivers.relational import ExecuteResult, Params

log = structlog.get_logger(__name__)

__all__ = ["PostgresRelationalDriver"]


class PostgresRelationalDriver:
    """Relational transport over a PostgreSQL connection pool (asyncpg).

    DSN resolution order: explicit ``dsn`` arg → ``spec.base_url`` →
    ``POSTGRES_DSN`` env var → ``DATABASE_URL`` env var.
    """

    def __init__(
        self,
        dsn: str | None = None,
        *,
        spec: DriverSpec | None = None,
        api_key: str | None = None,  # accepted for contract uniformity, unused
        name: str = "postgresql",
        min_size: int = 2,
        max_size: int = 10,
    ) -> None:
        resolved = (
            dsn or (spec.base_url if spec else None) or os.environ.get("POSTGRES_DSN") or os.environ.get("DATABASE_URL")
        )
        if not resolved:
            raise DriverInvalidRequest(
                "PostgresRelationalDriver needs a DSN: pass dsn=, set spec.base_url, POSTGRES_DSN, or DATABASE_URL",
                driver=name,
            )
        self._dsn = resolved
        self._name = spec.name if spec else name
        self._min_size = min_size
        self._max_size = max_size
        self._pool: Any = None  # asyncpg.Pool, typed as Any to avoid import-time dep

    @property
    def descriptor(self) -> DriverDescriptor:
        return DriverDescriptor(
            name=self._name,
            type="storage",
            modality="relational",
            source="local",
            capabilities=frozenset(),
            pricing_ref=None,
        )

    async def connect(self) -> None:
        try:
            import asyncpg
        except ImportError as exc:
            raise DriverInvalidRequest(
                "Install agentix[postgresql] to use the PostgreSQL driver",
                driver=self._name,
            ) from exc
        self._pool = await asyncpg.create_pool(
            dsn=self._dsn,
            min_size=self._min_size,
            max_size=self._max_size,
        )
        log.info("postgresql.pool_ready", name=self._name, dsn=self._dsn[:40])

    async def aclose(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    def _pool_or_raise(self) -> Any:
        if self._pool is None:
            raise RuntimeError("PostgresRelationalDriver.connect() not called")
        return self._pool

    def _translate(self, exc: Exception) -> Exception:
        msg = f"{type(exc).__name__}: {str(exc)[:200]}"
        # asyncpg exception names — check by string to avoid import-time dep
        t = type(exc).__name__
        if t in ("TooManyConnectionsError", "ConnectionDoesNotExistError", "CannotConnectNowError"):
            return DriverUnavailable(msg, driver=self._name)
        if t in (
            "UniqueViolationError",
            "ForeignKeyViolationError",
            "NotNullViolationError",
            "PostgresSyntaxError",
            "UndefinedTableError",
            "UndefinedColumnError",
        ):
            return DriverInvalidRequest(msg, driver=self._name)
        return DriverUnavailable(msg, driver=self._name)

    async def execute(self, sql: str, params: Params = ()) -> ExecuteResult:
        pool = self._pool_or_raise()
        try:
            result = await pool.execute(sql, *params)
            # asyncpg returns a status string like "INSERT 0 1"; parse rowcount
            rowcount = -1
            if isinstance(result, str):
                parts = result.split()
                if parts and parts[-1].isdigit():
                    rowcount = int(parts[-1])
            return ExecuteResult(lastrowid=None, rowcount=rowcount)
        except Exception as exc:
            raise self._translate(exc) from exc

    async def query(self, sql: str, params: Params = ()) -> list[dict[str, Any]]:
        pool = self._pool_or_raise()
        try:
            rows = await pool.fetch(sql, *params)
            return [dict(row) for row in rows]
        except Exception as exc:
            raise self._translate(exc) from exc

    async def query_one(self, sql: str, params: Params = ()) -> dict[str, Any] | None:
        pool = self._pool_or_raise()
        try:
            row = await pool.fetchrow(sql, *params)
            return dict(row) if row else None
        except Exception as exc:
            raise self._translate(exc) from exc

    async def commit(self) -> None:
        # asyncpg pools auto-commit; explicit commit is a no-op unless in a transaction.
        pass
