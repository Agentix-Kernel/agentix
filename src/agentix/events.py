"""In-process event bus used by both the CLI and the HTTP SSE surface.

v0.1 is single-node. A subscriber registers a queue, producers publish
events onto every active queue, subscribers drain on their own schedule.
No persistence — events are ephemeral and meant for live observation.

v0.2 bridges this in-process bus to the NATS JetStream broker (the worker
publishes Contract B v2 events onto the stream; apps subscribes).

Lives at the package root (not under ``cli/``) so the interface-agnostic
action layer, the broker worker, and the read-only HTTP surface can all
publish/subscribe without importing the CLI package (Locked #3).
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from ludo_shared import SessionEvent as _WireSessionEvent
from pydantic import ConfigDict, Field

from agentix.event_types import SCHEMA_VERSION


class SessionEvent(_WireSessionEvent):
    """One Contract B v2 lifecycle event in a session's stream.

    The wire envelope (6 fields, locked #430-D) is the canonical **shared** model
    (`ludo_shared.SessionEvent`, generated from `session-event.schema.json`); this adds the
    agent's construction defaults — auto ``at`` timestamp + default ``schema_version`` — and is
    frozen (immutable, hashable). ``type`` is one of :data:`agentix.event_types.EVENT_TYPES`;
    ``checkpoint_required`` is the per-event operator-review flag (reserved) — distinct from a
    resumable state checkpoint.
    """

    model_config = ConfigDict(extra="allow", frozen=True)

    at: str = Field(default_factory=lambda: datetime.now(tz=UTC).isoformat())
    schema_version: str = SCHEMA_VERSION


class SessionEventBus:
    """Per-session fan-out of events to N async subscribers."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[SessionEvent | None]]] = defaultdict(list)
        self._lock = asyncio.Lock()
        # Global sinks see EVERY published event regardless of session_id — the
        # broker worker registers one to forward the whole stream to NATS
        # without needing to subscribe per (action-minted) session id.
        self._global_sinks: list[Callable[[SessionEvent], Awaitable[None]]] = []

    def add_sink(self, sink: Callable[[SessionEvent], Awaitable[None]]) -> None:
        """Register a global sink invoked on every ``publish`` (e.g. NATS forward)."""
        self._global_sinks.append(sink)

    def remove_sink(self, sink: Callable[[SessionEvent], Awaitable[None]]) -> None:
        if sink in self._global_sinks:
            self._global_sinks.remove(sink)

    async def publish(self, event: SessionEvent) -> None:
        async with self._lock:
            queues = list(self._subscribers.get(event.session_id, ()))
        for q in queues:
            await q.put(event)
        for sink in list(self._global_sinks):
            await sink(event)

    async def close_session(self, session_id: str) -> None:
        """Send a ``None`` sentinel so every subscriber stops cleanly."""
        async with self._lock:
            queues = list(self._subscribers.get(session_id, ()))
        for q in queues:
            await q.put(None)

    async def subscribe(self, session_id: str) -> asyncio.Queue[SessionEvent | None]:
        q: asyncio.Queue[SessionEvent | None] = asyncio.Queue()
        async with self._lock:
            self._subscribers[session_id].append(q)
        return q

    async def unsubscribe(self, session_id: str, queue: asyncio.Queue[SessionEvent | None]) -> None:
        async with self._lock:
            if queue in self._subscribers.get(session_id, ()):
                self._subscribers[session_id].remove(queue)


# Module-level singleton — simple enough for v0.1's single-node scope.
bus = SessionEventBus()


def event_as_sse(event: SessionEvent) -> bytes:
    """Render an event as a single ``text/event-stream`` frame."""
    import json

    payload = event.model_dump(mode="json")
    return f"event: {event.type}\ndata: {json.dumps(payload, default=str)}\n\n".encode()
