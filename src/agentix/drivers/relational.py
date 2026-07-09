"""Relational driver family — the storage-type SQL transport.

Phase 2 of the storage driver split (see ``drivers/object_store.py`` for
the doctrine): ``SqliteStore`` stays the semantic layer — the session/
turn/cost vocabulary, schema DDL and migrations — while the connection
strategy and raw statement execution live behind this protocol. SQLite is
the landed backend; MySQL/Postgres arrive as new adapters (app-side or
kernel) without touching the store.

Honesty note: the kernel's DDL is written in the SQLite dialect (WAL,
FTS5, ``PRAGMA table_info``). A non-SQLite adapter satisfies this
protocol, but the *kernel store's* schema does not port automatically —
a dialect layer is app work, stated in ``docs/drivers.md``, not silently
claimed.

Rows are returned as plain ``dict[str, Any]`` — backend-neutral, no
driver-specific row types leak upward.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from agentix.drivers.base import Driver

__all__ = ["ExecuteResult", "RelationalDriver"]

Params = tuple[Any, ...] | list[Any]


@dataclass(frozen=True)
class ExecuteResult:
    """Outcome of a write statement.

    ``lastrowid`` is the backend-assigned row id of the last INSERT
    (None when the backend or statement yields none); ``rowcount`` is
    the number of affected rows (-1 when unknown).
    """

    lastrowid: int | None = None
    rowcount: int = -1


@runtime_checkable
class RelationalDriver(Driver, Protocol):
    """Protocol every relational adapter implements — storage-type,
    ``modality="relational"``.

    Error contract: adapters classify once — lock/busy contention and
    connectivity → ``DriverUnavailable`` (retryable); constraint
    violations and malformed SQL → ``DriverInvalidRequest``.
    """

    async def connect(self) -> None:
        """Open the underlying connection/pool. Idempotence is the
        adapter's choice; the kernel store calls it once."""
        ...

    async def execute(self, sql: str, params: Params = ()) -> ExecuteResult:
        """Run one statement (DDL or write) and return its outcome."""
        ...

    async def query(self, sql: str, params: Params = ()) -> list[dict[str, Any]]:
        """Run a SELECT and fetch all rows as dicts."""
        ...

    async def query_one(self, sql: str, params: Params = ()) -> dict[str, Any] | None:
        """Run a SELECT and fetch the first row, or None."""
        ...

    async def commit(self) -> None:
        """Flush pending writes. Transaction scoping beyond commit()
        (savepoints, explicit BEGIN) is deliberately not in the protocol
        until a consumer needs it — don't generalize early."""
        ...
