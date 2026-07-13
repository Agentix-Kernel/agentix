"""``agentix.sync`` (#70) — the blocking facade over the async kernel.

Covers the KernelLoop lifecycle (round-trip, deadline-cancel, fork/pid
guard), the facade's admission gate, and one end-to-end pass over real
stores: SqliteStore + MinioStore on the local-fs object driver, an Engine
with a scripted dispatcher, session create → turn → resume.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest
from agentix.drivers.adapters.intrinsic.local_fs_object import LocalObjectStoreDriver

from agentix.core.engine import Engine
from agentix.core.types import Message, Turn
from agentix.drivers.session import current_session_id
from agentix.storage import MinioStore, SqliteStore
from agentix.sync import KernelLoop, SyncDeadlineExceeded, SyncFacade, SyncFacadeBusy

# ── KernelLoop ───────────────────────────────────────────────────────


def test_kernel_loop_submit_roundtrip() -> None:
    kl = KernelLoop(thread_name="test-loop-roundtrip")
    kl.start()
    kl.start()  # idempotent
    try:

        async def add(a: int, b: int) -> int:
            return a + b

        assert kl.submit(add(2, 3)) == 5
        assert kl.running
    finally:
        kl.stop()
    assert not kl.running


def test_kernel_loop_unstarted_raises() -> None:
    kl = KernelLoop()

    async def never() -> None:  # pragma: no cover - must not run
        raise AssertionError

    with pytest.raises(RuntimeError, match="not started"):
        kl.submit(never())


def test_kernel_loop_deadline_cancels_and_loop_survives() -> None:
    kl = KernelLoop(thread_name="test-loop-deadline")
    kl.start()
    try:
        with pytest.raises(SyncDeadlineExceeded):
            kl.submit(asyncio.sleep(30), timeout_seconds=0.05)

        # The loop is still serviceable after a cancelled call.
        async def ping() -> str:
            return "pong"

        assert kl.submit(ping()) == "pong"
    finally:
        kl.stop()


def test_kernel_loop_refuses_foreign_pid_and_restarts_cold() -> None:
    """A forked child must not submit onto the parent's loop. Spoof the
    recorded pid to simulate the child, then verify start() rebuilds cold."""
    kl = KernelLoop(thread_name="test-loop-fork")
    kl.start()
    parent_loop = kl.loop
    kl._pid = (kl._pid or 0) + 1  # simulate: we are not the recording process

    async def ping() -> str:
        return "pong"

    with pytest.raises(RuntimeError, match="pid"):
        kl.submit(ping())

    # The at-fork hook does this in a real child.
    kl._reset_after_fork()
    kl.start()
    try:
        assert kl.loop is not parent_loop
        assert kl.submit(ping()) == "pong"
    finally:
        kl.stop()
        parent_loop.call_soon_threadsafe(parent_loop.stop)  # orphaned test loop


# ── SyncFacade ───────────────────────────────────────────────────────


def _facade(tmp_path: Path, **kwargs: object) -> SyncFacade:
    sqlite = SqliteStore(tmp_path / "kernel.sqlite3")
    minio = MinioStore(driver=LocalObjectStoreDriver(tmp_path / "objects"))
    return SyncFacade(sqlite=sqlite, minio=minio, **kwargs)  # type: ignore[arg-type]


def test_facade_end_to_end_create_run_resume(tmp_path: Path) -> None:
    """create → run_turn (real checkpoint through the local object driver)
    → resume_or_create restores the conversation."""
    seen_session_ids: list[str | None] = []

    async def dispatcher(turn: Turn) -> Turn:
        # session_scope must be bound around the chain (driver attribution).
        seen_session_ids.append(current_session_id.get())
        turn.assistant_message = Message(role="assistant", content="done")
        return turn

    facade = _facade(tmp_path)
    facade.start()
    try:
        engine = Engine(
            sqlite=facade._sqlite,
            minio=facade._minio,
            middlewares=[],
            dispatcher=dispatcher,
        )
        session, resumed = facade.resume_or_create(customer_id="c1", control_plane_id="cp-e2e")
        assert resumed is False

        turn = facade.run_turn(engine, session, Message(role="user", content="hello"))
        assert turn.status == "ok"
        assert seen_session_ids == [session.id]
        assert [m.role for m in session.messages] == ["user", "assistant"]

        # Same binding resumes with the conversation intact — the caller must
        # not re-seed (resume_or_create contract).
        restored, resumed = facade.resume_or_create(customer_id="c1", control_plane_id="cp-e2e")
        assert resumed is True
        assert restored.id == session.id
        assert [m.role for m in restored.messages] == ["user", "assistant"]
        assert restored.turn_index == 1
    finally:
        facade.close()


def test_facade_admission_busy(tmp_path: Path) -> None:
    facade = _facade(tmp_path, admission_limit=1, admission_timeout_seconds=0.05)
    facade.start()
    try:
        holding = threading.Event()

        async def hold() -> None:
            holding.set()
            await asyncio.sleep(1.0)

        occupant = threading.Thread(target=lambda: facade.run(hold()))
        occupant.start()
        assert holding.wait(timeout=5.0)

        # The occupant holds the loop AND the admission slot: submission
        # happens inside the gate, so the slot frees only when hold() ends.
        async def quick() -> None:
            return None

        with pytest.raises(SyncFacadeBusy):
            facade.run(quick())
        occupant.join(timeout=5.0)
    finally:
        facade.close()


def test_facade_start_reaps_expired_leases(tmp_path: Path) -> None:
    """A previous process life left a leased ``running`` session behind —
    facade start() must reap it to ``failed``."""
    facade = _facade(tmp_path)
    facade.start()
    session = facade.create_session(customer_id="c1")

    async def _lease_in_the_past() -> None:
        await facade._sqlite.claim_session_lease(session.id, leased_by="dead-worker", ttl_seconds=-60)

    facade.run(_lease_in_the_past())
    facade.close()

    reborn = _facade(tmp_path)
    reborn.start()
    try:

        async def _status() -> str:
            row = await reborn._sqlite.get_session(session.id)
            assert row is not None
            return str(row["status"])

        assert reborn.run(_status()) == "failed"
    finally:
        reborn.close()
