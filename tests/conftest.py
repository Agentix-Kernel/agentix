"""Root pytest fixtures shared across the unit + integration suites.

Centralizes the boilerplate that was copy-pasted into ~100 test modules:
an in-memory MinIO (``minio``) and a fresh SQLite store (``sqlite`` /
``sqlite_store`` — same body, two names by historical convention).

pytest resolves fixtures by name from the nearest conftest, so a test
module that needs a *different* fixture (e.g. one that pre-creates a
session) simply defines its own — that local definition overrides these.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentix.storage import SqliteStore
from tests._fakes import _FakeMinio


@pytest.fixture
def minio() -> _FakeMinio:
    return _FakeMinio()


@pytest.fixture
async def sqlite(tmp_path: Path) -> AsyncIterator[SqliteStore]:
    store = SqliteStore(tmp_path / "t.db")
    await store.initialize()
    try:
        yield store
    finally:
        await store.close()


@pytest.fixture
async def sqlite_store(tmp_path: Path) -> AsyncIterator[SqliteStore]:
    store = SqliteStore(tmp_path / "t.db")
    await store.initialize()
    try:
        yield store
    finally:
        await store.close()
