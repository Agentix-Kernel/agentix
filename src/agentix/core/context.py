"""Context budget + compression primitives.

Defines the shared ``ContextBudget`` (token cap + keep-recent) and the default
``summarise_oldest_tool_results`` compression strategy: when the running context
crosses the token threshold, the oldest tool exchanges collapse into a single
summary message. Compression is **pluggable** (strategy injected into
``ContextManager``) and **deterministic** (same input → same output), so
resuming from a checkpoint produces an identical context.

The window owner that assembles + budgets + compresses using these primitives is
``ContextManager`` (``core/context_manager.py``); ``TokenBudget`` middleware calls
its ``compress_if_needed`` before aborting on budget.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from agentix.core.types import Message

# Max chars to keep per elided tool_result in the compression
# summary. 200 is enough for the shape of a typical output (model
# name, record count, minio_key) without bloating the summary message
# back past the budget.
_ELIDED_SNIPPET_CHARS = 200

CompressionStrategy = Callable[[list[Message], int], list[Message]]


@dataclass
class ContextBudget:
    """Token budget for a single LLM call."""

    max_input_tokens: int = 16_000
    # Turns below this count are kept verbatim even under compression.
    keep_recent: int = 4


def summarise_oldest_tool_results(
    messages: list[Message],
    max_input_tokens: int,
) -> list[Message]:
    """Default compression — replace oldest tool results with a summary.

    Algorithm:
      * The first ``system`` message is always kept.
      * The most recent ``keep_recent`` non-system messages are kept.
      * Everything in between is collapsed into a single ``user`` summary
        message enumerating the elided tool calls.

    The goal is to bound input tokens without losing the conversational
    shape of the most recent exchange. More aggressive compression
    strategies can be plugged in here.
    """
    if _estimate_tokens(messages) <= max_input_tokens:
        return list(messages)

    keep_recent = 4  # keep the last N non-system messages verbatim
    system_msgs = [m for m in messages if m.role == "system"]
    non_system = [m for m in messages if m.role != "system"]

    if len(non_system) <= keep_recent:
        # Nothing to elide — return as-is (we're over budget but compression
        # can't shrink further without dropping the latest exchange).
        return list(messages)

    elided = non_system[:-keep_recent]
    recent = non_system[-keep_recent:]

    # Include a truncated snippet of each elided tool_result in the
    # summary so the agent retains *some* signal about what happened,
    # not just tool names. Dropping content entirely forces a later
    # planning step to re-invoke the same tool to re-acquire facts that
    # were already in context, doubling cost.
    tool_call_names: list[str] = []
    elided_results: list[str] = []
    for m in elided:
        if m.role == "assistant":
            for tc in m.tool_calls:
                tool_call_names.append(tc.name)
        elif m.role == "tool":
            snippet = (m.content or "").strip()
            if len(snippet) > _ELIDED_SNIPPET_CHARS:
                snippet = snippet[:_ELIDED_SNIPPET_CHARS] + "…[truncated]"
            elided_results.append(f"  - result@{m.tool_call_id}: {snippet}")

    summary_body = (
        f"[context-compressed] {len(elided)} earlier messages elided, "
        f"including tool calls: {', '.join(tool_call_names) or '(none)'}."
    )
    if elided_results:
        summary_body += "\n\nElided tool_result snippets (truncated):\n" + "\n".join(elided_results)
    summary = Message(role="user", content=summary_body)
    return [*system_msgs, summary, *recent]


def _estimate_tokens(messages: list[Message]) -> int:
    return sum(m.token_estimate() for m in messages)


# ``ContextBuilder`` was retired (agentix#20): assembly moved to the dispatcher's
# ContextManager path and ``compress_if_needed`` now lives on ``ContextManager``.
# ``ContextBudget`` + ``summarise_oldest_tool_results`` above remain the shared
# budget type + default compression strategy that ContextManager reuses.
