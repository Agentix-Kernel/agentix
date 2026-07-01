"""Per-tool call-count cap — agent-thrash circuit breaker.

Complements:mod:`agentix.core.middleware.loop_detection`:
* LoopDetection catches "same tool + same args N times in a ROW"
  (back-to-back identical calls).
* This middleware catches "same tool N times TOTAL across the session"
  (slow-burn thrash where the agent calls a tool many times with
  varied args — exhaustive but unproductive).

The kernel ships **no** per-tool caps — tool names are an app concept. Every
tool falls through to ``fallback_cap`` unless the app supplies explicit caps
via ``ToolCallCountCapMiddleware(per_tool_caps={...})`` (the migration app sizes
its Odoo tools this way).

When any tool exceeds its cap, the turn is marked aborted with a
descriptive reason — same clean-abort pattern as TokenBudget.
"""

from __future__ import annotations

from collections import OrderedDict, defaultdict

import structlog

from agentix.core.middleware.base import Next
from agentix.core.types import Turn

log = structlog.get_logger(__name__)


# The kernel names no app tools; apps pass ``per_tool_caps``. Caps are sized so
# they fire BEFORE the global ``--max-tool-iterations`` limit on pathological
# thrash — the abort_reason then names the offending tool rather than just
# reporting iteration exhaustion.
_DEFAULT_CAPS: dict[str, int] = {}
_DEFAULT_FALLBACK_CAP = 50

_DEFAULT_MAX_SESSIONS = 512


class ToolCallCountCapMiddleware:
    """Aborts when any single tool's session call count crosses its cap.

    Per-session counters live in an LRU-capped OrderedDict so a
    long-running FastAPI process doesn't leak one dict entry per
    session ever seen (same hygiene as LoopDetectionMiddleware).
    """

    name = "ToolCallCountCap"

    def __init__(
        self,
        *,
        per_tool_caps: dict[str, int] | None = None,
        fallback_cap: int = _DEFAULT_FALLBACK_CAP,
        max_sessions: int = _DEFAULT_MAX_SESSIONS,
    ) -> None:
        self._caps: dict[str, int] = dict(_DEFAULT_CAPS)
        if per_tool_caps:
            self._caps.update(per_tool_caps)
        self._fallback_cap = fallback_cap
        # session_id → tool_name → count
        self._counts: OrderedDict[str, dict[str, int]] = OrderedDict()
        self._max_sessions = max_sessions

    async def __call__(self, turn: Turn, next_: Next) -> Turn:
        # Run the inner chain first — we count CALLS that already
        # happened. Pre-flight blocking would require predicting which
        # tools the LLM is about to call, which we can't do.
        result = await next_(turn)

        counts = self._counts_for(result.session_id)
        for tcr in result.tool_call_results:
            counts[tcr.tool_name] += 1
            cap = self._caps.get(tcr.tool_name, self._fallback_cap)
            if counts[tcr.tool_name] > cap:
                reason = (
                    f"tool {tcr.tool_name!r} called {counts[tcr.tool_name]} times "
                    f"this session (cap={cap}) — agent thrash, aborting"
                )
                # Clean abort — never raise from middleware. Caller
                # (engine + outer runner) treats abort as a real session
                # outcome and persists the turn normally.
                result.abort(reason)
                log.warning(
                    "tool_count_cap.aborted",
                    session_id=result.session_id,
                    tool_name=tcr.tool_name,
                    count=counts[tcr.tool_name],
                    cap=cap,
                )
                return result
        return result

    def _counts_for(self, session_id: str) -> dict[str, int]:
        """Return (or create) the per-tool counter dict for this session.
        LRU-evicts the oldest session when the cap is exceeded."""
        if session_id in self._counts:
            self._counts.move_to_end(session_id)
            return self._counts[session_id]
        if len(self._counts) >= self._max_sessions:
            self._counts.popitem(last=False)
        bucket: dict[str, int] = defaultdict(int)
        self._counts[session_id] = bucket
        return bucket

    def evict(self, session_id: str) -> None:
        """Operator-callable hook — drop the in-memory counter for a
        finished session. Optional; LRU eviction handles it eventually."""
        self._counts.pop(session_id, None)
