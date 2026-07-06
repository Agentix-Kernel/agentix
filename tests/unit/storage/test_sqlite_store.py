"""Unit tests for SqliteStore — real aiosqlite against a tmp file."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentix.storage import SqliteStore


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[SqliteStore]:
    s = SqliteStore(tmp_path / "ludo.db")
    await s.initialize()
    try:
        yield s
    finally:
        await s.close()


# ───────────────────────────────── schema ──────────────────────────────────


@pytest.mark.asyncio
async def test_initialize_enables_wal_and_fk(tmp_path: Path) -> None:
    s = SqliteStore(tmp_path / "x.db")
    await s.initialize()
    try:
        assert s.path.exists()
        db = s._conn()
        async with db.execute("PRAGMA journal_mode") as cur:
            row = await cur.fetchone()
            assert row is not None and row[0].lower() == "wal"
        async with db.execute("PRAGMA foreign_keys") as cur:
            row = await cur.fetchone()
            assert row is not None and row[0] == 1
    finally:
        await s.close()


@pytest.mark.asyncio
async def test_initialize_sets_busy_timeout(tmp_path: Path) -> None:
    """A busy timeout is set so a concurrent writer waits rather than
    failing with SQLITE_BUSY (agentix#39 / isolation.md I2)."""
    s = SqliteStore(tmp_path / "bt.db")
    await s.initialize()
    try:
        async with s._conn().execute("PRAGMA busy_timeout") as cur:
            row = await cur.fetchone()
            assert row is not None and row[0] == 30000
    finally:
        await s.close()


@pytest.mark.asyncio
async def test_second_initialize_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "x.db"
    s1 = SqliteStore(path)
    await s1.initialize()
    await s1.create_session(session_id="A", customer_id="c1")
    await s1.close()

    s2 = SqliteStore(path)
    await s2.initialize()
    got = await s2.get_session("A")
    assert got is not None
    assert got["customer_id"] == "c1"
    await s2.close()


# ─────────────────────────────── sessions ──────────────────────────────────


@pytest.mark.asyncio
async def test_create_and_get_session(store: SqliteStore) -> None:
    await store.create_session(
        session_id="S1",
        customer_id="example",
        app_meta={"source_version": "V9", "target_version": "V18"},
    )
    got = await store.get_session("S1")
    assert got is not None
    assert got["id"] == "S1"
    assert got["customer_id"] == "example"
    assert json.loads(got["app_meta"]) == {"source_version": "V9", "target_version": "V18"}
    assert got["status"] == "running"
    assert got["total_cost_usd"] == 0.0


@pytest.mark.asyncio
async def test_update_session_accumulates_tokens_and_cost(store: SqliteStore) -> None:
    await store.create_session(session_id="S1", customer_id="example")
    await store.update_session("S1", input_tokens_delta=100, cost_usd_delta=0.5)
    await store.update_session("S1", output_tokens_delta=200, cost_usd_delta=0.25)
    got = await store.get_session("S1")
    assert got is not None
    assert got["total_input_tokens"] == 100
    assert got["total_output_tokens"] == 200
    assert got["total_cost_usd"] == 0.75


@pytest.mark.asyncio
async def test_update_session_marks_ended(store: SqliteStore) -> None:
    await store.create_session(session_id="S1", customer_id="example")
    await store.update_session("S1", status="completed", mark_ended=True)
    got = await store.get_session("S1")
    assert got is not None
    assert got["status"] == "completed"
    assert got["ended_at"] is not None


@pytest.mark.asyncio
async def test_list_sessions_filters_by_customer_and_status(store: SqliteStore) -> None:
    for sid, cust, status in [
        ("A", "example", "running"),
        ("B", "example", "completed"),
        ("C", "eco", "running"),
    ]:
        await store.create_session(session_id=sid, customer_id=cust, status=status)  # type: ignore[arg-type]
    all_running = {s["id"] for s in await store.list_sessions(status="running")}
    assert all_running == {"A", "C"}
    by_customer = {s["id"] for s in await store.list_sessions(customer_id="example")}
    assert by_customer == {"A", "B"}


# ───────────────────────────────── turns ───────────────────────────────────


@pytest.mark.asyncio
async def test_append_turn_returns_id(store: SqliteStore) -> None:
    await store.create_session(session_id="S1", customer_id="example")
    t1 = await store.append_turn(
        session_id="S1",
        turn_index=0,
        role="assistant",
        content_inline="hello",
        input_tokens=10,
        output_tokens=20,
    )
    t2 = await store.append_turn(session_id="S1", turn_index=1, role="user", content_inline="reply")
    assert t1 < t2


@pytest.mark.asyncio
async def test_cascade_delete_removes_turns(store: SqliteStore) -> None:
    await store.create_session(session_id="S1", customer_id="example")
    await store.append_turn(session_id="S1", turn_index=0, role="assistant", content_inline="x")
    db = store._conn()
    await db.execute("DELETE FROM sessions WHERE id = 'S1'")
    await db.commit()
    async with db.execute("SELECT COUNT(*) FROM turns WHERE session_id = 'S1'") as cur:
        row = await cur.fetchone()
    assert row is not None and row[0] == 0


# ───────────────────────────────── FTS5 ────────────────────────────────────


@pytest.mark.asyncio
async def test_fts_search_hits_turns(store: SqliteStore) -> None:
    await store.create_session(session_id="S1", customer_id="example")
    await store.append_turn(session_id="S1", turn_index=0, role="assistant", content_inline="the quick brown fox")
    await store.append_turn(session_id="S1", turn_index=1, role="assistant", content_inline="lazy dog sleeping")
    results = await store.search_turns("quick")
    assert len(results) == 1
    assert "quick brown fox" in results[0]["content_inline"]


@pytest.mark.asyncio
async def test_fts_respects_session_filter(store: SqliteStore) -> None:
    await store.create_session(session_id="S1", customer_id="example")
    await store.create_session(session_id="S2", customer_id="eco")
    await store.append_turn(session_id="S1", turn_index=0, role="assistant", content_inline="res.partner mapped")
    await store.append_turn(session_id="S2", turn_index=0, role="assistant", content_inline="res.partner mapped")
    filtered = await store.search_turns("res.partner", session_id="S1")
    assert len(filtered) == 1
    assert filtered[0]["session_id"] == "S1"


@pytest.mark.asyncio
async def test_fts_index_survives_turn_deletion(store: SqliteStore) -> None:
    await store.create_session(session_id="S1", customer_id="example")
    turn_id = await store.append_turn(
        session_id="S1", turn_index=0, role="assistant", content_inline="ephemeral content"
    )
    # Before delete
    assert len(await store.search_turns("ephemeral")) == 1
    db = store._conn()
    await db.execute("DELETE FROM turns WHERE id = ?", (turn_id,))
    await db.commit()
    assert await store.search_turns("ephemeral") == []


# ───────────────────────────── safety + errors ─────────────────────────────


@pytest.mark.asyncio
async def test_append_safety_event_counts(store: SqliteStore) -> None:
    await store.create_session(session_id="S1", customer_id="example")
    turn_id = await store.append_turn(session_id="S1", turn_index=0, role="tool", tool_name="load_to_odoo")
    await store.append_safety_event(session_id="S1", kind="dry_run_block", turn_id=turn_id, tool_name="load_to_odoo")
    await store.append_safety_event(
        session_id="S1",
        kind="per_batch_verify_fail",
        turn_id=turn_id,
        tool_name="load_to_odoo",
        detail="expected 50 rows, got 48",
    )
    assert await store.count_safety_events("S1") == 2
    assert await store.count_safety_events("S1", kind="per_batch_verify_fail") == 1


@pytest.mark.asyncio
async def test_append_error_stores_all_fields(store: SqliteStore) -> None:
    await store.create_session(session_id="S1", customer_id="example")
    err_id = await store.append_error(
        session_id="S1",
        error_class="ValueError",
        error_message="boom",
        model="res.partner",
        external_id="ludo.example-res_partner-42",
    )
    assert err_id > 0


# ───────────────────────────── concurrency ─────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_turn_inserts(store: SqliteStore) -> None:
    await store.create_session(session_id="S1", customer_id="example")
    await asyncio.gather(
        *(
            store.append_turn(session_id="S1", turn_index=i, role="assistant", content_inline=f"msg-{i}")
            for i in range(20)
        )
    )
    db = store._conn()
    async with db.execute("SELECT COUNT(*) FROM turns WHERE session_id = 'S1'") as cur:
        row = await cur.fetchone()
    assert row is not None and row[0] == 20
    assert len(await store.search_turns("msg-5")) == 1


# ─────────────────── target health (PR-J) ───────────────────


@pytest.mark.asyncio
async def test_record_target_health_round_trips(store: SqliteStore) -> None:
    row_id = await store.record_target_health(url="http://x", ok=True)
    assert row_id > 0
    db = store._conn()
    async with db.execute("SELECT url, ok FROM target_health WHERE id = ?", (row_id,)) as cur:
        row = await cur.fetchone()
    assert row is not None
    assert row[0] == "http://x"
    assert row[1] == 1


@pytest.mark.asyncio
async def test_recent_target_failures_counts_consecutive_streak(store: SqliteStore) -> None:
    """Streak is counted back from the most recent — a success resets it."""
    url = "http://target"
    await store.record_target_health(url=url, ok=False, error_class="A")
    await store.record_target_health(url=url, ok=False, error_class="B")
    assert await store.recent_target_failures(url=url) == 2
    await store.record_target_health(url=url, ok=True)
    assert await store.recent_target_failures(url=url) == 0
    await store.record_target_health(url=url, ok=False, error_class="C")
    assert await store.recent_target_failures(url=url) == 1


@pytest.mark.asyncio
async def test_recent_target_failures_scoped_by_url(store: SqliteStore) -> None:
    await store.record_target_health(url="http://a", ok=False)
    await store.record_target_health(url="http://a", ok=False)
    await store.record_target_health(url="http://b", ok=True)
    assert await store.recent_target_failures(url="http://a") == 2
    assert await store.recent_target_failures(url="http://b") == 0
    assert await store.recent_target_failures(url="http://c") == 0


@pytest.mark.asyncio
async def test_schema_version_is_tracked(store: SqliteStore) -> None:
    """M18: a ``schema_version`` row exists after initialize, marking
    the live schema generation. Future v0.2 schema changes bump the
    constant and append a migration block in ``_apply_migrations``."""
    from agentix.storage.sqlite_store import _SCHEMA_VERSION

    async with store._conn().execute("SELECT MAX(version) FROM schema_version") as cur:
        row = await cur.fetchone()
    assert row is not None
    assert row[0] == _SCHEMA_VERSION


@pytest.mark.asyncio
async def test_schema_version_not_reinserted_on_reinit(tmp_path: Path) -> None:
    """M18: re-initialising an already-migrated DB must NOT insert a
    duplicate ``schema_version`` row."""
    db_path = tmp_path / "m18.db"
    store1 = SqliteStore(db_path)
    await store1.initialize()
    await store1.close()

    store2 = SqliteStore(db_path)
    await store2.initialize()
    async with store2._conn().execute("SELECT COUNT(*) FROM schema_version") as cur:
        row = await cur.fetchone()
    assert row is not None and row[0] == 1
    await store2.close()


@pytest.mark.asyncio
async def test_v5_to_v6_migration_adds_intervention_type_column(tmp_path: Path) -> None:
    """v5 → v6 migration: existing DB without `intervention_type` gets
    ALTERed to add it (default 'none'). Legacy sessions predate the
    metric and stay uncounted rather than being retroactively (and
    wrongly) classified."""
    import aiosqlite

    db_path = tmp_path / "v5.db"
    # A v5-shape DB: has target_models, no intervention_type.
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("""
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                source_version TEXT,
                target_version TEXT,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                total_input_tokens INTEGER NOT NULL DEFAULT 0,
                total_output_tokens INTEGER NOT NULL DEFAULT 0,
                total_cost_usd REAL NOT NULL DEFAULT 0.0,
                checkpoint TEXT,
                target_models TEXT NOT NULL DEFAULT '[]'
            )
        """)
        await conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL, applied_at TEXT)")
        await conn.execute("INSERT INTO schema_version VALUES (5, datetime('now'))")
        await conn.execute(
            "INSERT INTO sessions(id, customer_id, status, started_at) "
            "VALUES ('LEGACY', 'old', 'completed', datetime('now'))"
        )
        await conn.commit()

    s = SqliteStore(db_path)
    await s.initialize()
    try:
        got = await s.get_session("LEGACY")
        assert got is not None
        assert got["intervention_type"] == "none"
        # New sessions can be classified after the migration.
        await s.create_session(session_id="NEW", customer_id="new")
        await s.set_intervention_type("NEW", "novel")
        got2 = await s.get_session("NEW")
        assert got2 is not None
        assert got2["intervention_type"] == "novel"
    finally:
        await s.close()
