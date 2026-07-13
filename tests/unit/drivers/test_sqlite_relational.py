"""Unit tests for the SQLite relational driver — descriptor, verbs,
error mapping, seam construction, registry accessor, store delegation."""

from __future__ import annotations

from pathlib import Path

import pytest
from agentix.drivers.adapters.intrinsic.sqlite import SqliteRelationalDriver

from agentix.config import DriverSpec
from agentix.drivers import (
    DriverInvalidRequest,
    DriverRegistry,
    DriverUnavailable,
    RelationalDriver,
)


@pytest.fixture
async def driver(tmp_path: Path) -> SqliteRelationalDriver:
    d = SqliteRelationalDriver(tmp_path / "t.db")
    await d.connect()
    yield d
    await d.aclose()


# ───────────────────── descriptor + protocol ─────────────────────


def test_descriptor_is_storage_relational(tmp_path: Path) -> None:
    d = SqliteRelationalDriver(tmp_path / "t.db")
    assert d.descriptor.type == "storage"
    assert d.descriptor.modality == "relational"
    assert d.descriptor.source == "local"
    assert d.descriptor.pricing_ref is None


def test_protocol_structural_conformance(tmp_path: Path) -> None:
    assert isinstance(SqliteRelationalDriver(tmp_path / "t.db"), RelationalDriver)


# ───────────────────── verbs ─────────────────────


@pytest.mark.asyncio
async def test_execute_query_roundtrip(driver: SqliteRelationalDriver) -> None:
    await driver.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    res = await driver.execute("INSERT INTO t (name) VALUES (?)", ("a",))
    assert res.lastrowid == 1
    await driver.execute("INSERT INTO t (name) VALUES (?)", ("b",))
    await driver.commit()

    rows = await driver.query("SELECT * FROM t ORDER BY id")
    assert rows == [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
    one = await driver.query_one("SELECT name FROM t WHERE id = ?", (2,))
    assert one == {"name": "b"}
    assert await driver.query_one("SELECT name FROM t WHERE id = 99") is None


@pytest.mark.asyncio
async def test_connect_applies_wal(driver: SqliteRelationalDriver) -> None:
    row = await driver.query_one("PRAGMA journal_mode")
    assert row is not None and str(next(iter(row.values()))).lower() == "wal"


# ───────────────────── error mapping ─────────────────────


@pytest.mark.asyncio
async def test_malformed_sql_maps_to_invalid_request(driver: SqliteRelationalDriver) -> None:
    with pytest.raises(DriverInvalidRequest):
        await driver.execute("NOT VALID SQL")


@pytest.mark.asyncio
async def test_integrity_error_maps_to_invalid_request(driver: SqliteRelationalDriver) -> None:
    await driver.execute("CREATE TABLE u (id INTEGER PRIMARY KEY, k TEXT UNIQUE)")
    await driver.execute("INSERT INTO u (k) VALUES ('x')")
    with pytest.raises(DriverInvalidRequest):
        await driver.execute("INSERT INTO u (k) VALUES ('x')")


@pytest.mark.asyncio
async def test_locked_maps_to_unavailable(driver: SqliteRelationalDriver, monkeypatch: pytest.MonkeyPatch) -> None:
    import sqlite3

    async def _boom(*a: object, **k: object) -> None:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(driver.raw, "execute", _boom)
    with pytest.raises(DriverUnavailable) as exc_info:
        await driver.execute("SELECT 1")
    assert exc_info.value.retryable is True


# ───────────────────── seam construction ─────────────────────


def test_spec_construction(tmp_path: Path) -> None:
    spec = DriverSpec(
        name="ops-db",
        driver="sqlite-relational",
        type="storage",
        modality="relational",
        options=(("path", str(tmp_path / "ops.db")),),
    )
    d = SqliteRelationalDriver(spec=spec, api_key=None)
    assert d.descriptor.name == "ops-db"
    assert d.path == tmp_path / "ops.db"


def test_construction_without_path_or_spec_raises() -> None:
    with pytest.raises(DriverInvalidRequest):
        SqliteRelationalDriver()


# ───────────────────── registry accessor ─────────────────────


def test_registry_relational_accessor(tmp_path: Path) -> None:
    d = SqliteRelationalDriver(tmp_path / "t.db")
    reg = DriverRegistry()
    reg.register(d)
    assert reg.relational() is d


# ───────────────────── store delegation ─────────────────────


@pytest.mark.asyncio
async def test_sqlite_store_over_injected_driver(tmp_path: Path) -> None:
    """SqliteStore(driver=...) initializes schema and round-trips a session
    through the protocol verbs — the alternate-backend path."""
    from agentix.storage import SqliteStore

    d = SqliteRelationalDriver(tmp_path / "ops.db", name="ops")
    store = SqliteStore(driver=d)
    await store.initialize()
    try:
        await store.create_session(session_id="s1", customer_id="acme")
        got = await store.get_session("s1")
        assert got is not None and got["customer_id"] == "acme"
        assert store.driver is d
        # The sqlite-dialect escape hatch is live on the sqlite adapter.
        assert store._db is d.raw
    finally:
        await store.close()
