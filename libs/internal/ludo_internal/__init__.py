"""ludo_internal — INTERNAL-ONLY shared NATS transport for the private repos.

Vendored (byte-identical) by **ludo-agent + ludo-gateway ONLY**. NEVER vendor into the public
clients (`ludo-cli` / `ludo-desktop`): this holds broker/NATS internals, not client-safe code
— the opposite of `ludo_shared`, which is client-safe and may be vendored publicly (CRIE IE-2's
public/private split). The single duplicated bit was the JetStream stream-topology declaration +
connect, hand-kept in both repos with a "MUST match" comment; this makes it structural.

Drift guarded by `scripts/check_internal_drift.py` (agent + gateway roots only).
"""

from __future__ import annotations

from .nats_streams import connect, ensure_streams

__all__ = ["connect", "ensure_streams"]
