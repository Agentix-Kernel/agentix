"""ContextManager — the single owner of the per-turn model window.

Today "what goes in the model window each step" is assembled in several places:
the dispatcher (``_build_request`` copies history + injects working memory),
``context.py`` (compression), and ``TokenBudgetMiddleware`` (the budget check).
That scatter is the context-management CRIE finding — no one place decides what
enters the window, in what priority, and why.

``ContextManager`` consolidates that: one object that **assembles** the window in
priority-tier order, **compresses** it to budget, and emits a per-turn **X-ray**
describing every message (tier, role, tokens, reason) and the totals. It reuses
``context.py``'s ``ContextBudget`` + compression strategy rather than
reimplementing them (CRIE — one compression, one budget type).

This module is **additive**: it does not yet replace the dispatcher's inline
assembly. It mirrors that assembly exactly (working memory as a system message
inserted after the leading system prompt, then compress-to-budget) so the
dispatcher can be rewired onto it in a follow-up and the behaviour diffed one
step at a time. Tracks agentix#20; see docs/context.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from agentix.core.context import (
    CompressionStrategy,
    ContextBudget,
    _estimate_tokens,
    summarise_oldest_tool_results,
)
from agentix.core.types import Message

# Content marker the default compression strategy stamps on its summary message.
# Used only to label that message in the X-ray; assembly never depends on it.
_SUMMARY_MARKER = "[context-compressed]"


class Tier(IntEnum):
    """Window priority tiers — lower number survives longer under pressure.

    Mirrors the eviction order in docs/context.md:
    guardrails/safety > task/goal > working set > retrieved memory > history.
    The current window has three concrete kinds plus the compression summary;
    richer tiers (retrieved memory) slot in between as they are wired.
    """

    SYSTEM = 0  # leading system prompt(s) — never evicted
    WORKING_MEMORY = 1  # tried/failed/learned — kept as system, survives compression
    SUMMARY = 2  # stands in for elided history after compression
    HISTORY = 3  # conversation turns — first to be compressed away


@dataclass
class WindowEntry:
    """One assembled message plus why it is in the window (an X-ray row)."""

    tier: Tier
    role: str
    tokens: int
    reason: str


@dataclass
class AssembledContext:
    """Result of :meth:`ContextManager.assemble` — the messages to send to the
    provider plus the per-turn X-ray."""

    messages: list[Message]
    entries: list[WindowEntry] = field(default_factory=list)
    compressed: bool = False
    budget_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return sum(e.tokens for e in self.entries)

    def xray(self) -> dict[str, Any]:
        """JSON-serialisable snapshot of the window: totals + one row per
        message (tier name, role, token estimate, reason). For per-turn
        observability of exactly what the model saw and why."""
        return {
            "total_tokens": self.total_tokens,
            "budget_tokens": self.budget_tokens,
            "compressed": self.compressed,
            "over_budget": self.total_tokens > self.budget_tokens,
            "messages": [
                {"tier": e.tier.name, "role": e.role, "tokens": e.tokens, "reason": e.reason}
                for e in self.entries
            ],
        }


def _after_leading_system(messages: list[Message]) -> int:
    """Index just past the run of leading ``system`` messages — where working
    memory is inserted so the primary system prompt stays at index 0."""
    insert_at = 0
    for i, m in enumerate(messages):
        if m.role == "system":
            insert_at = i + 1
        else:
            break
    return insert_at


class ContextManager:
    """Owns the per-turn model window: assemble → compress → X-ray.

    Reuses ``context.py``'s budget + compression strategy (no duplication).
    Stateless across turns; construct once per run or per turn as convenient.
    """

    def __init__(
        self,
        *,
        budget: ContextBudget | None = None,
        compression: CompressionStrategy = summarise_oldest_tool_results,
    ) -> None:
        self.budget = budget or ContextBudget()
        self.compression = compression

    def assemble(
        self,
        base_messages: list[Message],
        *,
        working_memory_render: str | None = None,
        compress: bool = True,
    ) -> AssembledContext:
        """Build the window from ``base_messages`` (the turn's history, system
        prompt at index 0), fold in working memory, optionally compress to
        budget, and classify every surviving message for the X-ray.

        Mirrors the dispatcher's current ``_build_request`` assembly exactly:
        working memory becomes a ``system`` message inserted after the leading
        system prompt (so it survives compression, which keeps system messages).
        ``compress=False`` does assembly + X-ray only, leaving compression to
        whoever owns the budget step (today the ``TokenBudget`` middleware) —
        that is how the dispatcher adopts the manager without moving the
        compression seam.
        """
        messages = list(base_messages)

        # Working memory: a system message after the leading system prompt.
        wm_msg: Message | None = None
        if working_memory_render:
            wm_msg = Message(role="system", content=working_memory_render)
            messages.insert(_after_leading_system(messages), wm_msg)

        # Compress to budget (deterministic; same input → same output).
        if compress:
            before = _estimate_tokens(messages)
            final = self.compression(messages, self.budget.max_input_tokens)
            compressed = _estimate_tokens(final) < before
        else:
            final = messages
            compressed = False

        entries = [self._classify(m, wm_msg) for m in final]
        return AssembledContext(
            messages=final,
            entries=entries,
            compressed=compressed,
            budget_tokens=self.budget.max_input_tokens,
        )

    def _classify(self, m: Message, wm_msg: Message | None) -> WindowEntry:
        """Assign a tier + human reason to one surviving message. Identity is
        used to tell working memory from the primary system prompt (both are
        ``system``); the compression summary is detected by its content marker."""
        tokens = m.token_estimate()
        if wm_msg is not None and m is wm_msg:
            return WindowEntry(Tier.WORKING_MEMORY, m.role, tokens, "working memory (tried/failed/learned)")
        if m.role == "system":
            return WindowEntry(Tier.SYSTEM, m.role, tokens, "system prompt / guardrails")
        if m.role == "user" and (m.content or "").startswith(_SUMMARY_MARKER):
            return WindowEntry(Tier.SUMMARY, m.role, tokens, "compression summary (elided history)")
        return WindowEntry(Tier.HISTORY, m.role, tokens, "conversation history")
