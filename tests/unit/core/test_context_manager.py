"""Unit tests for ContextManager — the per-turn window owner (agentix#20).

Covers assembly order, working-memory injection, compression-to-budget, and the
window report. Pure in-memory; no store or provider.
"""

from __future__ import annotations

from agentix.core.context import ContextBudget
from agentix.core.context_manager import AssembledContext, ContextManager, Tier
from agentix.core.types import Message


def _history() -> list[Message]:
    """A system prompt followed by a few conversation turns."""
    return [
        Message(role="system", content="You are the migration agent."),
        Message(role="user", content="Migrate customer c1."),
        Message(role="assistant", content="Starting extract."),
        Message(role="user", content="ok"),
    ]


def test_assemble_passthrough_under_budget() -> None:
    cm = ContextManager()  # default 16k budget — comfortably above this window
    out = cm.assemble(_history())
    assert isinstance(out, AssembledContext)
    assert out.compressed is False
    assert [m.role for m in out.messages] == ["system", "user", "assistant", "user"]
    # The window report classifies the leading system message as SYSTEM, the rest as HISTORY.
    tiers = [e.tier for e in out.entries]
    assert tiers[0] is Tier.SYSTEM
    assert all(t is Tier.HISTORY for t in tiers[1:])


def test_working_memory_injected_after_system() -> None:
    cm = ContextManager()
    out = cm.assemble(_history(), working_memory_render="TRIED: extract failed on res.partner")
    # Working memory is a system message inserted right after the primary
    # system prompt (index 1), before any history.
    assert out.messages[1].role == "system"
    assert "TRIED" in (out.messages[1].content or "")
    assert out.entries[0].tier is Tier.SYSTEM
    assert out.entries[1].tier is Tier.WORKING_MEMORY
    assert out.entries[2].tier is Tier.HISTORY


def test_no_working_memory_when_blank() -> None:
    cm = ContextManager()
    out = cm.assemble(_history(), working_memory_render="")
    assert not any(e.tier is Tier.WORKING_MEMORY for e in out.entries)
    assert len(out.messages) == len(_history())


def test_compression_fires_over_budget_and_keeps_working_memory() -> None:
    # Tiny budget forces compression; >keep_recent non-system messages so the
    # strategy has something to elide.
    msgs = [Message(role="system", content="sys")]
    for i in range(8):
        msgs.append(Message(role="user", content=f"question {i} " * 20))
        msgs.append(Message(role="assistant", content=f"answer {i} " * 20))
    cm = ContextManager(budget=ContextBudget(max_input_tokens=50))
    out = cm.assemble(msgs, working_memory_render="LEARNED: batch size 200 is safe")

    assert out.compressed is True
    # Working memory (system) survives compression...
    assert any(e.tier is Tier.WORKING_MEMORY for e in out.entries)
    # ...and a compression summary now stands in for the elided history.
    assert any(e.tier is Tier.SUMMARY for e in out.entries)
    # System prompt is still first.
    assert out.entries[0].tier is Tier.SYSTEM


def test_compress_if_needed_shrinks_over_budget() -> None:
    """The budget step TokenBudget middleware calls: returns compressed messages
    + did=True only when the token estimate actually dropped."""
    msgs = [Message(role="system", content="sys")]
    for i in range(8):
        msgs.append(Message(role="user", content=f"q{i} " * 30))
        msgs.append(Message(role="assistant", content=f"a{i} " * 30))
    cm = ContextManager(budget=ContextBudget(max_input_tokens=40))
    out, did = cm.compress_if_needed(msgs)
    assert did is True
    assert len(out) < len(msgs)


def test_compress_if_needed_noop_under_budget() -> None:
    cm = ContextManager(budget=ContextBudget(max_input_tokens=100_000))
    msgs = _history()
    out, did = cm.compress_if_needed(msgs)
    assert did is False
    assert out == msgs


def test_compress_false_assembles_without_compressing() -> None:
    """compress=False (how the dispatcher calls it) folds in working memory but
    leaves the budget/compression step alone — every message is preserved even
    over budget, and nothing is marked compressed."""
    msgs = [Message(role="system", content="sys")]
    for i in range(8):
        msgs.append(Message(role="user", content=f"question {i} " * 20))
        msgs.append(Message(role="assistant", content=f"answer {i} " * 20))
    cm = ContextManager(budget=ContextBudget(max_input_tokens=50))
    out = cm.assemble(msgs, working_memory_render="LEARNED: x", compress=False)

    assert out.compressed is False
    # No summary — nothing was elided.
    assert not any(e.tier is Tier.SUMMARY for e in out.entries)
    # All originals + the working-memory message survive.
    assert len(out.messages) == len(msgs) + 1
    assert any(e.tier is Tier.WORKING_MEMORY for e in out.entries)


def test_window_report_totals_and_rows() -> None:
    cm = ContextManager(budget=ContextBudget(max_input_tokens=9000))
    out = cm.assemble(_history(), working_memory_render="TRIED: x")
    report = out.window_report()
    assert report["budget_tokens"] == 9000
    assert report["total_tokens"] == out.total_tokens
    assert report["over_budget"] is False
    assert len(report["messages"]) == len(out.messages)
    # Every row carries the four report fields.
    row = report["messages"][0]
    assert set(row) == {"tier", "role", "tokens", "reason"}
    assert row["tier"] == "SYSTEM"
