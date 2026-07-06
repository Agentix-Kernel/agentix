"""TokenBudget — aborts the session when cumulative cost crosses the cap.

The cap is a *USD* budget. Cost accounting runs in ``CostTracking``
(which sits directly outside this middleware); we consult the session
totals **after** the current turn has recorded its cost, then decide
whether to abort the next turn.

Two levers before giving up:

1. Ask ``ContextManager.compress_if_needed`` to shrink the input. If it
   can shrink further, ``turn.compressed = True`` and we proceed — the
   next turn will re-check the budget.
2. If compression can't help, mark ``turn.status = "aborted"`` with a
   descriptive reason. This is a *clean* abort — never raise. The engine
   persists the aborted turn normally.

The compression step runs through ``ContextManager`` — the one window/budget
owner (agentix#20). A default is constructed when none is injected, so the
compress-before-abort lever is always live (it was previously dead whenever a
caller omitted the builder).
"""

from __future__ import annotations

import structlog

from agentix.core.context_manager import ContextManager
from agentix.core.middleware.base import Next
from agentix.core.types import Turn
from agentix.storage import SqliteStore

log = structlog.get_logger(__name__)


class TokenBudgetMiddleware:
    """Aborts when session cumulative cost crosses the cap."""

    name = "TokenBudget"

    def __init__(
        self,
        *,
        sqlite: SqliteStore,
        budget_usd: float = 25.0,
        warn_threshold: float = 0.80,
        context_manager: ContextManager | None = None,
    ) -> None:
        self._sqlite = sqlite
        self._budget_usd = budget_usd
        self._warn_threshold = warn_threshold
        self._warned: set[str] = set()
        # Default-construct so the compress-before-abort lever is always wired.
        self._context_manager = context_manager or ContextManager()

    async def __call__(self, turn: Turn, next_: Next) -> Turn:
        # ── BEFORE: if already over budget, try to compress. If we can't
        # compress further, abort cleanly without invoking the downstream
        # chain (no LLM call, no tool execution).
        current_cost = await self._current_cost(turn.session_id)

        # Proactive warning at ``warn_threshold`` * cap. Operators who
        # miscalibrate the cap at session start see a log line with the
        # concrete spend before the hard-stop, and once per session
        # (not once per turn) so the stream stays readable.
        warn_at = self._budget_usd * self._warn_threshold
        if current_cost >= warn_at and current_cost < self._budget_usd and turn.session_id not in self._warned:
            self._warned.add(turn.session_id)
            log.warning(
                "budget.near_cap",
                session_id=turn.session_id,
                cost=round(current_cost, 4),
                cap=self._budget_usd,
                threshold=self._warn_threshold,
            )

        if current_cost >= self._budget_usd:
            if turn.input_messages:
                compressed, did = self._context_manager.compress_if_needed(turn.input_messages)
                if did:
                    turn.input_messages = compressed
                    turn.compressed = True
                    log.info(
                        "budget.compressed",
                        session_id=turn.session_id,
                        turn=turn.turn_index,
                        before=len(compressed) + 1,
                        after=len(compressed),
                    )
                    return await next_(turn)
            turn.abort(f"budget exceeded: cumulative ${current_cost:.4f} >= cap ${self._budget_usd:.2f}")
            log.warning(
                "budget.aborted",
                session_id=turn.session_id,
                turn=turn.turn_index,
                cost=round(current_cost, 6),
                cap=self._budget_usd,
            )
            return turn

        return await next_(turn)

    async def _current_cost(self, session_id: str) -> float:
        row = await self._sqlite.get_session(session_id)
        if row is None:
            return 0.0
        return float(row["total_cost_usd"])
