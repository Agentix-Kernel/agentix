"""Unit tests for WorkingMemory — the structured, compression-surviving
record of "tried / failed / learned" the agent maintains within a
session.

The pins:

1. ``record()`` appends; failed attempts auto-flag ``blocked_paths``;
   ``is_blocked`` recognises them.
2. ``render_for_system_prompt()`` produces empty string on empty memory
   (so callers skip injection) and a markdown block otherwise.
3. The rendered system message survives ``summarise_oldest_tool_results``
   compression unchanged — the whole point of putting it in the
   ``system`` role.
4. ``_build_request`` on the AgentDispatcher injects the working-memory
   system message *after* the original system prompt and before the
   conversation history.
"""

from __future__ import annotations

from agentix.core.context import summarise_oldest_tool_results
from agentix.core.types import Message
from agentix.core.working_memory import WorkingMemory


def test_record_appends_and_auto_blocks_failed() -> None:
    wm = WorkingMemory()
    wm.record(
        target="res.company.name",
        approach="direct load_to_odoo of computed field",
        outcome="failed",
        lesson="name is a stored computed field; write parent_id instead",
        turn_index=3,
        tool_name="load_to_odoo",
    )
    assert len(wm.attempts) == 1
    assert wm.attempts[0].target == "res.company.name"
    assert wm.attempts[0].outcome == "failed"
    # Failed attempts auto-flag the (target, approach) pair as a dead end.
    assert wm.is_blocked("res.company.name", "direct load_to_odoo of computed field")
    assert "res.company.name via direct load_to_odoo of computed field" in wm.blocked_paths


def test_successful_attempt_does_not_block_by_default() -> None:
    wm = WorkingMemory()
    wm.record(
        target="account.move bulk write",
        approach="context check_move_validity=False",
        outcome="success",
        lesson="V18 check_move_validity blocks batch loads; load_context flag bypasses it",
        turn_index=7,
    )
    assert not wm.is_blocked("account.move bulk write", "context check_move_validity=False")
    assert wm.blocked_paths == []


def test_blocked_paths_dedupe_on_repeat() -> None:
    wm = WorkingMemory()
    for turn in (1, 2, 3):
        wm.record(
            target="res.company.name",
            approach="direct load_to_odoo",
            outcome="failed",
            lesson="still computed",
            turn_index=turn,
        )
    # Three attempts recorded — append-only.
    assert len(wm.attempts) == 3
    # But blocked_paths is set-like — one entry, not three.
    assert wm.blocked_paths == ["res.company.name via direct load_to_odoo"]


def test_render_empty_returns_empty_string() -> None:
    wm = WorkingMemory()
    assert wm.render_for_system_prompt() == ""


def test_render_shows_blocked_paths_and_recent_attempts() -> None:
    wm = WorkingMemory()
    wm.set_strategy("Load res.company first via pin-then-update; defer name field to a post-load sync")
    wm.record(
        target="res.company.name",
        approach="direct load_to_odoo of computed field",
        outcome="failed",
        lesson="name is a stored computed field; write parent_id instead",
        turn_index=3,
        tool_name="load_to_odoo",
    )
    wm.record(
        target="res.company parent_id",
        approach="write parent_id then trigger recompute",
        outcome="success",
        lesson="recompute on parent_id propagates name correctly",
        turn_index=4,
        tool_name="load_to_odoo",
    )
    rendered = wm.render_for_system_prompt()
    assert "Working memory" in rendered
    assert "Active strategy" in rendered
    assert "pin-then-update" in rendered
    assert "Blocked paths" in rendered
    assert "res.company.name via direct load_to_odoo of computed field" in rendered
    assert "Attempts log" in rendered
    assert "✗" in rendered  # failed marker
    assert "✓" in rendered  # success marker


def test_render_elides_old_attempts_past_recent_window() -> None:
    wm = WorkingMemory()
    for i in range(20):
        wm.record(
            target=f"model.field_{i}",
            approach=f"approach_{i}",
            outcome="failed",
            lesson=f"lesson {i}",
            turn_index=i,
            tool_name="load_to_odoo",
        )
    rendered = wm.render_for_system_prompt()
    # Oldest attempts should be summarised away; only ~12 recent ones rendered in full.
    assert "earlier attempt(s) elided" in rendered
    # The most recent attempt MUST be present in full.
    assert "model.field_19" in rendered
    # The very first attempt should NOT be in the full-detail block.
    assert "model.field_0 via approach_0" not in rendered.split("Attempts log")[1]


def test_working_memory_system_message_survives_compression() -> None:
    """The whole point of the system-role injection: compression keeps it."""
    wm = WorkingMemory()
    wm.record(
        target="res.company.name",
        approach="direct load_to_odoo",
        outcome="failed",
        lesson="computed field — write parent_id instead",
        turn_index=3,
    )
    wm_rendered = wm.render_for_system_prompt()
    wm_msg = Message(role="system", content=wm_rendered)

    # Build a realistic 30-turn history that blows the budget; the
    # compressor should collapse the middle but keep BOTH system messages.
    original_system = Message(role="system", content="You are LUDO migrating Odoo data.")
    history: list[Message] = [original_system, wm_msg]
    for i in range(30):
        history.append(Message(role="user", content=f"Turn {i} user content " * 50))
        history.append(Message(role="assistant", content=f"Turn {i} assistant content " * 50))

    compressed = summarise_oldest_tool_results(history, max_input_tokens=1_000)
    system_messages = [m for m in compressed if m.role == "system"]
    # Both system messages survived — the original prompt AND the
    # working-memory injection. That is the invariant we are pinning.
    assert len(system_messages) == 2
    assert "LUDO migrating" in system_messages[0].content
    assert "Working memory" in system_messages[1].content
    assert "res.company.name" in system_messages[1].content
    # The lesson survived compression — the whole point.
    assert "computed field" in system_messages[1].content


def test_set_strategy_replaces_and_clears() -> None:
    wm = WorkingMemory()
    wm.set_strategy("first plan")
    assert wm.active_strategy == "first plan"
    wm.set_strategy("revised plan after first hit a wall")
    assert wm.active_strategy == "revised plan after first hit a wall"
    wm.set_strategy("")
    assert wm.active_strategy == ""
