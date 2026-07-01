"""Contract B v2 event types — the agent→control-plane lifecycle stream.

The canonical enum is the **shared** ``ludo_shared.EventType`` (generated from
``session-event.schema.json``, locked #430-D). This module re-exports it plus the named
module-level aliases the action layer uses (`SESSION_STARTED` …) — they ARE the EventType
members now, so there is no hand-kept list to drift. The agent must only emit these.
"""

from __future__ import annotations

from ludo_shared import EVENT_TYPES, EventType

# Session lifecycle (the whole run).
SESSION_STARTED = EventType.SESSION_STARTED
SESSION_END = EventType.SESSION_END

# Per-Model boundaries (one Job acts on one Model).
MODEL_STARTED = EventType.MODEL_STARTED
MODEL_COMPLETED = EventType.MODEL_COMPLETED

# Per-Job boundaries (a Session decomposes into N Jobs; emitted by the worker).
JOB_STARTED = EventType.JOB_STARTED
JOB_COMPLETED = EventType.JOB_COMPLETED
JOB_FAILED = EventType.JOB_FAILED

# Per-Turn boundaries (one Cortex round-trip + tool dispatch) — customer-facing.
TURN_STARTED = EventType.TURN_STARTED
TURN_COMPLETED = EventType.TURN_COMPLETED

# Safety + operator-decision milestones.
SAFETY_EVENT = EventType.SAFETY_EVENT
CHECKPOINT_REQUESTED = EventType.CHECKPOINT_REQUESTED  # reserved (operator review milestone)

# Current Contract B envelope version (breaking rename of kind→type lands here).
SCHEMA_VERSION = "2.0"

__all__ = [
    "CHECKPOINT_REQUESTED",
    "EVENT_TYPES",
    "JOB_COMPLETED",
    "JOB_FAILED",
    "JOB_STARTED",
    "MODEL_COMPLETED",
    "MODEL_STARTED",
    "SAFETY_EVENT",
    "SCHEMA_VERSION",
    "SESSION_END",
    "SESSION_STARTED",
    "TURN_COMPLETED",
    "TURN_STARTED",
    "EventType",
]
