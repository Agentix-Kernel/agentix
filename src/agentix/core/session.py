"""Session — the checkpoint-first, resumable unit of an agent run.

The ``Session`` object carries conversation history, progress, and token /
cost totals. It is **app-agnostic**: generic operational fields plus an
``app_meta`` dict the app fills with its own scope (the migration app stores
source/target version + target models there). Persistence is split across the
storage layer:

* Operational metadata (tenant, status, totals, named checkpoint, app_meta)
  lives in SQLite.
* The full state blob (messages, tool results, cursors) is JSON-serialised
  to MinIO under ``checkpoints/{session_id}/{checkpoint}.json``.

``save`` writes both — SQLite row first, then MinIO blob. ``resume_from``
reads both and rebuilds the in-memory ``Session``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agentix.core.types import Message
from agentix.core.working_memory import WorkingMemory
from agentix.storage import MinioStore, SqliteStore
from agentix.storage.sqlite_store import SessionStatus


class Session(BaseModel):
    """The complete state of an agent session (app-agnostic)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: f"s_{uuid.uuid4().hex[:12]}")
    customer_id: str
    status: SessionStatus = "running"
    turn_index: int = 0
    messages: list[Message] = Field(default_factory=list)
    checkpoint: str | None = None
    budget_usd: float = 200.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    # App-specific session scope (opaque to the kernel). The migration app puts
    # ``source_version`` / ``target_version`` / ``target_models`` here. Persisted
    # to ``sessions.app_meta`` as JSON.
    app_meta: dict[str, Any] = Field(default_factory=dict)
    # Control-plane binding: the gateway-assigned Migration id this Session runs
    # (stored control-plane-side as ``ludo_session_id``). Lets the gateway
    # correlate its Migration with the agent Session for resumable SSE +
    # observability without a side mapping. NULL for local/no-control-plane runs.
    control_plane_id: str | None = None
    # A2A delegation link: the Session that spawned this one (self-referential).
    # NULL for top-level runs. Crossing rules (only distilled context crosses a
    # boundary) are enforced above the store, not by this field.
    parent_session_id: str | None = None
    # Structured "tried / failed / learned" log that survives per-turn
    # context compression. Rendered into a system-role message before
    # each LLM call by ``agent_dispatcher`` so the agent sees its own
    # lessons every turn. See ``core/working_memory.py``.
    working_memory: WorkingMemory = Field(default_factory=WorkingMemory)

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serialisable snapshot of the full session state."""
        return self.model_dump(mode="json")


async def create_session(
    sqlite: SqliteStore,
    *,
    customer_id: str,
    budget_usd: float = 200.0,
    app_meta: dict[str, Any] | None = None,
    control_plane_id: str | None = None,
    parent_session_id: str | None = None,
) -> Session:
    """Create a new session, persisting the SQLite row.

    ``customer_id`` is the opaque per-tenant id (no PII). ``app_meta`` is the
    app's own session scope, stored opaquely in ``sessions.app_meta`` (the
    migration app puts source/target version + target models there). Defaults
    to ``{}`` for sessions with no pre-declared scope — probes, free-form loops.

    ``control_plane_id`` binds this Session to the control-plane Migration id
    (the gateway's ``ludo_session_id``); pass it on the redelivery path so the
    gateway can project a resumable stream. ``parent_session_id`` names the
    spawning Session for A2A delegation. Both default to NULL (top-level, local).
    """
    session = Session(
        customer_id=customer_id,
        budget_usd=budget_usd,
        app_meta=dict(app_meta or {}),
        control_plane_id=control_plane_id,
        parent_session_id=parent_session_id,
    )
    await sqlite.create_session(
        session_id=session.id,
        customer_id=session.customer_id,
        status=session.status,
        app_meta=session.app_meta,
        control_plane_id=session.control_plane_id,
        parent_session_id=session.parent_session_id,
    )
    return session


async def save(
    session: Session,
    *,
    sqlite: SqliteStore,
    minio: MinioStore,
    checkpoint: str = "latest",
) -> str:
    """Persist a session.

    Write MinIO first, then SQLite. If the process dies between the two,
    we end up with an unreferenced checkpoint blob in MinIO — harmless;
    ``resume_from`` looks up the pointer in SQLite and the orphan is
    garbage-collected by bucket lifecycle. The reverse order would leave
    SQLite pointing at a checkpoint blob that never made it to storage —
    ``resume_from`` would 500 with "checkpoint not found" even though
    the session row says it's there.

    Callers should only invoke ``save(..., checkpoint=<named>)`` at
    phase boundaries; the engine persists ``checkpoint="latest"`` after
    every turn automatically.
    """
    key = MinioStore.key_checkpoint(session.customer_id, session.id, checkpoint)
    session.checkpoint = checkpoint
    # 1. MinIO first — the blob is what resume_from will actually read.
    await minio.put_json(key, session.snapshot())
    # 2. SQLite second — flipping the pointer AFTER the blob exists.
    await sqlite.update_session(
        session.id,
        status=session.status,
        checkpoint=checkpoint,
    )
    return key


async def resume_from(
    session_id: str,
    *,
    sqlite: SqliteStore,
    minio: MinioStore,
    checkpoint: str = "latest",
) -> Session:
    """Rebuild a Session from its checkpoint blob. Raises if not found."""
    row = await sqlite.get_session(session_id)
    if row is None:
        raise LookupError(f"session {session_id!r} not found in SQLite")
    key = MinioStore.key_checkpoint(str(row["customer_id"]), session_id, checkpoint)
    snapshot = await minio.get_json(key)
    return Session.model_validate(snapshot)
