"""NATS JetStream topology — the one declaration shared by the agent worker and the gateway.

Both private repos must declare the SAME streams/subjects (Contract B transport). The names come
from the vendored `ludo_shared` (canonical: `ludo-init/constants/cluster.yaml`); this module owns
the *declaration* + connect so the two repos can't drift on the `add_stream` shape. `nats` is
imported lazily so importing this module needs no dependency (stub modes stay dependency-free).
"""

from __future__ import annotations

from typing import Any

from ludo_shared import (
    EVENTS_STREAM,
    EVENTS_SUBJECT_PREFIX,
    JOBS_CANCEL_SUBJECT,
    JOBS_STREAM,
    JOBS_SUBJECT,
)


async def connect(url: str) -> Any:
    """Open a NATS connection (lazy import of the optional `nats` dependency)."""
    import nats

    return await nats.connect(url)


async def ensure_streams(js: Any) -> None:
    """Idempotently declare the job-ingress + event-egress streams.

    First declarer wins; a compatible re-declare by the other repo is a no-op."""
    import nats.js.errors as js_errors

    for name, subjects in (
        (JOBS_STREAM, [JOBS_SUBJECT, JOBS_CANCEL_SUBJECT]),
        (EVENTS_STREAM, [f"{EVENTS_SUBJECT_PREFIX}.>"]),
    ):
        try:
            await js.add_stream(name=name, subjects=subjects)
        except js_errors.BadRequestError:
            pass  # already exists with a compatible config
