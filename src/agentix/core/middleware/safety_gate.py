"""SafetyGate chain-position marker for the middleware ordering.

``SafetyGateMarker`` is a pass-through middleware that exists **only** to
hold a slot in the per-turn ``MIDDLEWARE_ORDER``. The real safety
enforcement — dry-run intercept, verifier invocation, rollback-on-drift
— is the app's per-tool SafetyGate implementation built on the kernel
base ``agentix.tools.safety.SafetyGate`` and runs per tool call, which
happens inside the agent dispatcher rather than the turn-level
middleware chain. The kernel names the contract, never a concrete app
module.

Why the split:
  * A per-turn middleware can't see individual tool calls. A turn can
    include zero, one, or many mutating tool calls; enforcement has to
    wrap each one.
  * Putting the marker in ``MIDDLEWARE_ORDER`` lets the engine refuse
    chains that accidentally omit safety (e.g. a user assembling a
    custom middleware stack).

Named ``SafetyGateMarker`` rather than ``SafetyGateMiddleware`` so the
no-op marker isn't confused for the real enforcement. The ``.name``
attribute stays ``"SafetyGate"`` so the ordering contract is unchanged.
"""

from __future__ import annotations

from agentix.core.middleware.base import Next
from agentix.core.types import Turn


class SafetyGateMarker:
    """Chain-position marker; real enforcement is the app's SafetyGate tool-wrapper."""

    name = "SafetyGate"

    async def __call__(self, turn: Turn, next_: Next) -> Turn:
        return await next_(turn)


# Deprecated alias retained so external consumers don't break on upgrade.
SafetyGateMiddleware = SafetyGateMarker
