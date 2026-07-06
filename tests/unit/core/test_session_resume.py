"""Unit tests for the resume-on-redelivery seam — get_session_by_control_plane_id
+ resume_or_create. Real SqliteStore against a tmp file, fake in-memory MinIO."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentix.core.session import create_session, resume_or_create, save
from agentix.storage import SqliteStore
from tests._fakes import _FakeMinio


@pytest.fixture
async def sqlite(tmp_path: Path) -> AsyncIterator[SqliteStore]:
    s = SqliteStore(tmp_path / "resume.db")
    await s.initialize()
    try:
        yield s
    finally:
        await s.close()


# ─────────────────────── get_session_by_control_plane_id ────────────────────


@pytest.mark.asyncio
async def test_lookup_returns_none_when_unbound(sqlite: SqliteStore) -> None:
    await sqlite.create_session(session_id="S1", customer_id="c1")  # no control_plane_id
    assert await sqlite.get_session_by_control_plane_id("mig_x") is None


@pytest.mark.asyncio
async def test_lookup_returns_latest_for_shared_id(sqlite: SqliteStore) -> None:
    """The compose path binds several per-model Sessions to one Migration id;
    the lookup returns the most recently started."""
    await sqlite.create_session(session_id="S1", customer_id="c1", control_plane_id="mig_1")
    await sqlite.create_session(session_id="S2", customer_id="c1", control_plane_id="mig_1")
    got = await sqlite.get_session_by_control_plane_id("mig_1")
    assert got is not None
    assert got["id"] == "S2"


# ─────────────────────────────── resume_or_create ──────────────────────────


@pytest.mark.asyncio
async def test_creates_fresh_when_no_prior(sqlite: SqliteStore) -> None:
    minio = _FakeMinio()
    session, resumed = await resume_or_create(
        sqlite, minio, customer_id="c1", control_plane_id="mig_new"
    )
    assert resumed is False
    assert session.control_plane_id == "mig_new"
    # persisted + discoverable by the binding
    row = await sqlite.get_session_by_control_plane_id("mig_new")
    assert row is not None and row["id"] == session.id


@pytest.mark.asyncio
async def test_resumes_existing_checkpointed_session(sqlite: SqliteStore) -> None:
    minio = _FakeMinio()
    # First run: create + advance state + checkpoint.
    first = await create_session(sqlite, customer_id="c1", control_plane_id="mig_r")
    first.turn_index = 3
    first.app_meta = {"note": "halfway"}
    await save(first, sqlite=sqlite, minio=minio, checkpoint="latest")

    # Redelivery: same control-plane id resumes the very same Session.
    resumed_session, resumed = await resume_or_create(
        sqlite, minio, customer_id="c1", control_plane_id="mig_r"
    )
    assert resumed is True
    assert resumed_session.id == first.id
    assert resumed_session.turn_index == 3
    assert resumed_session.app_meta == {"note": "halfway"}


@pytest.mark.asyncio
async def test_terminal_session_starts_fresh(sqlite: SqliteStore) -> None:
    """A completed run is terminal — a redelivery starts a new Session under the
    same binding rather than reviving a finished one."""
    minio = _FakeMinio()
    first = await create_session(sqlite, customer_id="c1", control_plane_id="mig_done")
    await save(first, sqlite=sqlite, minio=minio, checkpoint="latest")
    await sqlite.update_session(first.id, status="completed")

    session, resumed = await resume_or_create(
        sqlite, minio, customer_id="c1", control_plane_id="mig_done"
    )
    assert resumed is False
    assert session.id != first.id


@pytest.mark.asyncio
async def test_falls_through_when_checkpoint_blob_missing(sqlite: SqliteStore) -> None:
    """Row says resumable but the blob is gone — don't wedge the job; create a
    fresh Session instead of raising."""
    minio = _FakeMinio()
    # Point the row at a checkpoint that was never written to MinIO.
    await sqlite.create_session(session_id="S_ghost", customer_id="c1", control_plane_id="mig_ghost")
    await sqlite.update_session("S_ghost", checkpoint="latest")

    session, resumed = await resume_or_create(
        sqlite, minio, customer_id="c1", control_plane_id="mig_ghost"
    )
    assert resumed is False
    assert session.id != "S_ghost"
