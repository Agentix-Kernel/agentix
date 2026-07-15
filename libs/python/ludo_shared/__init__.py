"""ludo_shared — canonical cross-repo Python types + transport helpers.

Vendored (byte-identical copy) by the Python repos, the same way `contracts/` and
`constants/cluster.yaml` are. The wire types + broker constants in `_generated.py` are emitted
from the contracts by `scripts/gen_shared.py` — never hand-edit them; regenerate instead.
`sse.py` is hand-written. Drift is guarded by `scripts/check_shared_drift.py`.

Scope: client-safe (no secrets, no engine internals) so the public clients may vendor it. The
internal NATS broker client is NOT here — it stays between the private repos (see CRIE IE-2).
"""

from __future__ import annotations

from ._generated import (
    EVENT_TYPES,
    EVENTS_STREAM,
    EVENTS_SUBJECT_PREFIX,
    JOBS_CANCEL_SUBJECT,
    JOBS_STREAM,
    JOBS_SUBJECT,
    MIGRATION_STATES,
    NATS_URL,
    EventType,
    JobMessage,
    JobType,
    SessionEvent,
    event_subject,
    migration_state_label,
)
from .introspection import (
    INTROSPECT_BLUEPRINTS,
    INTROSPECT_BLUEPRINTS_GET,
    INTROSPECT_ESCALATIONS,
    INTROSPECT_HEALTHZ,
    INTROSPECT_MEMORY_ADVISE,
    INTROSPECT_MEMORY_CATALOGUE,
    INTROSPECT_MEMORY_RENAMES,
    INTROSPECT_MEMORY_STATS,
    INTROSPECT_MEMORY_TRAJECTORIES_SEARCH,
)
from .sse import decode_sse, encode_sse

__all__ = [
    "EVENTS_STREAM",
    "EVENTS_SUBJECT_PREFIX",
    "EVENT_TYPES",
    "EventType",
    "JOBS_CANCEL_SUBJECT",
    "JOBS_STREAM",
    "JOBS_SUBJECT",
    "MIGRATION_STATES",
    "JobMessage",
    "JobType",
    "NATS_URL",
    "SessionEvent",
    "decode_sse",
    "encode_sse",
    "event_subject",
    "migration_state_label",
    "INTROSPECT_HEALTHZ",
    "INTROSPECT_ESCALATIONS",
    "INTROSPECT_BLUEPRINTS",
    "INTROSPECT_BLUEPRINTS_GET",
    "INTROSPECT_MEMORY_CATALOGUE",
    "INTROSPECT_MEMORY_RENAMES",
    "INTROSPECT_MEMORY_STATS",
    "INTROSPECT_MEMORY_TRAJECTORIES_SEARCH",
    "INTROSPECT_MEMORY_ADVISE",
]
