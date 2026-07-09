"""SQLite relational driver — the landed relational transport.

Owns what used to be inlined in ``storage/sqlite_store.py``: the single
long-lived ``aiosqlite`` connection and the connection-time PRAGMAs (WAL,
NORMAL sync, foreign keys, 30s busy timeout — a concurrent writer from a
2nd process waits instead of failing with SQLITE_BUSY; agentix#39 /
isolation.md I2: the driver is now the one home of connection strategy).

Error classification happens here, once: lock/busy contention →
``DriverUnavailable`` (retryable); ``IntegrityError`` and malformed SQL →
``DriverInvalidRequest``.

``raw`` exposes the underlying ``aiosqlite.Connection`` as the
**sqlite-dialect escape hatch** for seam-#10 store subclasses whose
migrations need cursor-level access. It exists only on this adapter —
code using it is knowingly sqlite-bound.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import aiosqlite
import structlog

from agentix.config import DriverSpec
from agentix.drivers.base import (
    DriverDescriptor,
    DriverError,
    DriverInvalidRequest,
    DriverUnavailable,
)
from agentix.drivers.relational import ExecuteResult, Params

log = structlog.get_logger(__name__)

__all__ = ["SqliteRelationalDriver"]


class SqliteRelationalDriver:
    """Relational transport over one SQLite file.

    Construction: convenience ``SqliteRelationalDriver(path)`` (how
    ``SqliteStore`` builds its default) or the seam contract
    ``SqliteRelationalDriver(spec=spec, api_key=None)`` — path from
    ``spec.base_url`` or ``spec.options["path"]``; SQLite has no secret,
    ``api_key`` is accepted and ignored for contract uniformity.
    """

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        spec: DriverSpec | None = None,
        api_key: str | None = None,
        name: str = "sqlite",
    ) -> None:
        if path is None:
            if spec is None:
                raise DriverInvalidRequest("SqliteRelationalDriver needs a path or a DriverSpec", driver=name)
            path = spec.base_url or dict(spec.options).get("path", "")
            name = spec.name
        if not str(path):
            raise DriverInvalidRequest("SqliteRelationalDriver: empty database path", driver=name)
        self.path = Path(path)
        self._name = name
        self._db: aiosqlite.Connection | None = None

    @property
    def descriptor(self) -> DriverDescriptor:
        return DriverDescriptor(
            name=self._name,
            type="storage",
            modality="relational",
            source="local",
            capabilities=frozenset({"wal", "fts5"}),
            pricing_ref=None,
        )

    # ── lifecycle ───────────────────────────────────────────────────

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        # A concurrent writer (e.g. a 2nd worker process on the same WAL file)
        # waits up to 30s for the lock instead of failing immediately with
        # SQLITE_BUSY. Explicit + higher than the implicit sqlite3 5s
        # connect-timeout default (agentix#39 / isolation.md I2).
        await self._db.execute("PRAGMA busy_timeout=30000")

    async def aclose(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def raw(self) -> aiosqlite.Connection:
        """The sqlite-dialect escape hatch (adapter-specific, not protocol)."""
        if self._db is None:
            raise RuntimeError("SqliteRelationalDriver.connect() not called")
        return self._db

    # ── error classification (once, here) ───────────────────────────

    def _translate(self, exc: Exception) -> DriverError:
        msg = f"{type(exc).__name__}: {str(exc)[:200]}"
        if isinstance(exc, sqlite3.OperationalError) and ("locked" in str(exc).lower() or "busy" in str(exc).lower()):
            return DriverUnavailable(msg, driver=self._name)
        return DriverInvalidRequest(msg, driver=self._name)

    # ── verbs ───────────────────────────────────────────────────────

    async def execute(self, sql: str, params: Params = ()) -> ExecuteResult:
        try:
            cur = await self.raw.execute(sql, params)
            result = ExecuteResult(
                lastrowid=cur.lastrowid,
                rowcount=cur.rowcount if cur.rowcount is not None else -1,
            )
            await cur.close()
            return result
        except sqlite3.Error as exc:
            raise self._translate(exc) from exc

    async def query(self, sql: str, params: Params = ()) -> list[dict[str, Any]]:
        try:
            async with self.raw.execute(sql, params) as cur:
                rows = await cur.fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            raise self._translate(exc) from exc

    async def query_one(self, sql: str, params: Params = ()) -> dict[str, Any] | None:
        try:
            async with self.raw.execute(sql, params) as cur:
                row = await cur.fetchone()
            return dict(row) if row else None
        except sqlite3.Error as exc:
            raise self._translate(exc) from exc

    async def commit(self) -> None:
        try:
            await self.raw.commit()
        except sqlite3.Error as exc:
            raise self._translate(exc) from exc
