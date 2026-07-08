"""Session lease + orphan reaper — isolation.md I7 (schema v14)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentix.storage import SqliteStore


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[SqliteStore]:
    s = SqliteStore(tmp_path / "lease.db")
    await s.initialize()
    try:
        yield s
    finally:
        await s.close()


@pytest.mark.asyncio
async def test_claim_and_renew_lease(store: SqliteStore) -> None:
    await store.create_session(session_id="S1", customer_id="c1")
    await store.claim_session_lease("S1", leased_by="worker-a", ttl_seconds=300)
    row = await store.get_session("S1")
    assert row is not None
    assert row["leased_by"] == "worker-a"
    first_expiry = row["lease_expires_at"]
    assert first_expiry is not None

    # Renew pushes the expiry out and keeps the owner.
    await store.renew_session_lease("S1", ttl_seconds=600)
    row = await store.get_session("S1")
    assert row is not None
    assert row["leased_by"] == "worker-a"
    assert row["lease_expires_at"] > first_expiry


@pytest.mark.asyncio
async def test_reap_transitions_expired_running_to_failed(store: SqliteStore) -> None:
    await store.create_session(session_id="dead", customer_id="c1")
    # Lease already in the past (worker died mid-run).
    await store.claim_session_lease("dead", leased_by="worker-x", ttl_seconds=-10)

    reaped = await store.reap_expired_sessions()
    assert reaped == ["dead"]
    row = await store.get_session("dead")
    assert row is not None
    assert row["status"] == "failed"
    assert row["ended_at"] is not None


@pytest.mark.asyncio
async def test_reap_ignores_unleased_and_live(store: SqliteStore) -> None:
    # Unleased (NULL lease) — single-flight/local; never reaped.
    await store.create_session(session_id="unleased", customer_id="c1")
    # Live lease well into the future.
    await store.create_session(session_id="live", customer_id="c1")
    await store.claim_session_lease("live", leased_by="w", ttl_seconds=600)
    # Expired lease but already completed — not 'running', so not reaped.
    await store.create_session(session_id="done", customer_id="c1")
    await store.claim_session_lease("done", leased_by="w", ttl_seconds=-10)
    await store.update_session("done", status="completed")

    reaped = await store.reap_expired_sessions()
    assert reaped == []
    assert (await store.get_session("unleased"))["status"] == "running"  # type: ignore[index]
    assert (await store.get_session("live"))["status"] == "running"  # type: ignore[index]


@pytest.mark.asyncio
async def test_v14_migration_adds_lease_columns(tmp_path: Path) -> None:
    """A legacy v13 DB (no lease columns) is migrated in place."""
    import aiosqlite

    path = tmp_path / "legacy13.db"
    db = await aiosqlite.connect(path)
    await db.execute(
        "CREATE TABLE schema_version (version INTEGER NOT NULL, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    await db.execute(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, status TEXT NOT NULL,
            started_at TEXT NOT NULL, ended_at TEXT,
            total_input_tokens INTEGER NOT NULL DEFAULT 0,
            total_output_tokens INTEGER NOT NULL DEFAULT 0,
            total_cost_usd REAL NOT NULL DEFAULT 0.0, checkpoint TEXT,
            app_meta TEXT NOT NULL DEFAULT '{}', intervention_type TEXT NOT NULL DEFAULT 'none',
            outcome TEXT, control_plane_id TEXT, parent_session_id TEXT
        )
        """
    )
    await db.execute("INSERT INTO schema_version (version) VALUES (13)")
    await db.execute(
        "INSERT INTO sessions (id, customer_id, status, started_at) VALUES ('old', 'c1', 'running', '2026-01-01T00:00:00+00:00')"
    )
    await db.commit()
    await db.close()

    s = SqliteStore(path)
    await s.initialize()
    try:
        cols = await s._session_columns()
        assert "lease_expires_at" in cols
        assert "leased_by" in cols
        old = await s.get_session("old")
        assert old is not None and old["lease_expires_at"] is None
    finally:
        await s.close()
