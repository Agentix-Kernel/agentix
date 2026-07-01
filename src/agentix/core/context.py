"""Context assembly and compression.

Builds the per-turn LLM context — a flat ``list[Message]`` starting with
a system message plus the relevant slice of conversation history. When
the running context crosses a token threshold the compression strategy
replaces the oldest tool exchanges with a single summary message.

Compression is **pluggable** (strategy injected at ContextBuilder
construction) and **deterministic** (same input → same output), so
resuming from a checkpoint produces an identical context.

The compression entry point is exposed as ``compress_if_needed`` so
``TokenBudgetMiddleware`` can request compression before giving up.
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


class ContextBuilder:
    """Assembles per-turn context with a pluggable compression strategy."""

    def __init__(
        self,
        system_prompt: str,
        *,
        budget: ContextBudget | None = None,
        compression: CompressionStrategy = summarise_oldest_tool_results,
    ) -> None:
        self.system_prompt = system_prompt
        self.budget = budget or ContextBudget()
        self.compression = compression

    def build(self, history: list[Message]) -> list[Message]:
        """Prepend the system prompt to ``history`` in deterministic order.

        The caller (usually the engine) is responsible for passing history
        in the order it was accumulated; this method does not re-sort.
        """
        system = Message(role="system", content=self.system_prompt)
        return [system, *history]

    def compress_if_needed(self, messages: list[Message]) -> tuple[list[Message], bool]:
        """Apply the compression strategy if over budget.

        Returns ``(compressed, did_compress)``. ``did_compress`` is True
        iff compression actually reduced the token estimate. Comparing
        message count before/after is only a proxy — a strategy that
        shrinks message *bodies* without changing count would report
        did_compress=False incorrectly, and ``TokenBudgetMiddleware``
        would abort prematurely. Token delta is the right primitive.
        """
        before_tokens = _estimate_tokens(messages)
        compressed = self.compression(messages, self.budget.max_input_tokens)
        after_tokens = _estimate_tokens(compressed)
        return compressed, after_tokens < before_tokens
