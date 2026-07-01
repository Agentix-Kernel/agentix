"""Unit tests for ToolCallCountCapMiddleware (#176 follow-up A)."""

from __future__ import annotations

import pytest

from agentix.core.middleware.tool_count_cap import ToolCallCountCapMiddleware
from agentix.core.types import ToolCallResult, Turn


def _turn(*tool_names: str, session_id: str = "s1") -> Turn:
    """Synthesise a Turn with the given tool calls already executed."""
    return Turn(
        session_id=session_id,
        turn_index=0,
        input_messages=[],
        tool_call_results=[
            ToolCallResult(call_id=f"c_{i}", tool_name=name, ok=True) for i, name in enumerate(tool_names)
        ],
    )


async def _passthrough_next(turn: Turn) -> Turn:
    """Inner-chain stand-in — returns the turn unchanged."""
    return turn


# ──────────────────────── below cap ────────────────────────


@pytest.mark.asyncio
async def test_below_cap_does_not_abort() -> None:
    """A tool called few times → turn passes through cleanly."""
    mw = ToolCallCountCapMiddleware()
    turn = _turn("inspect_model", "lookup_known_fix")
    result = await mw(turn, _passthrough_next)
    assert result.status == "pending"  # not aborted
    assert result.abort_reason is None


# ──────────────────────── operator override ────────────


@pytest.mark.asyncio
async def test_operator_can_override_cap() -> None:
    """Custom per-tool caps replace defaults entirely (no merge surprise)."""
    mw = ToolCallCountCapMiddleware(per_tool_caps={"inspect_model": 2})
    await mw(_turn("inspect_model"), _passthrough_next)
    await mw(_turn("inspect_model"), _passthrough_next)
    abort = await mw(_turn("inspect_model"), _passthrough_next)
    assert abort.status == "aborted"
    assert "cap=2" in (abort.abort_reason or "")


@pytest.mark.asyncio
async def test_fallback_cap_for_unlisted_tools() -> None:
    """Tools not in the per-tool dict use fallback_cap (default 50)."""
    mw = ToolCallCountCapMiddleware(fallback_cap=3)
    for _ in range(3):
        await mw(_turn("custom_skill"), _passthrough_next)
    abort = await mw(_turn("custom_skill"), _passthrough_next)
    assert abort.status == "aborted"
    assert "cap=3" in (abort.abort_reason or "")


# ──────────────────────── per-session isolation ────────


@pytest.mark.asyncio
async def test_separate_sessions_have_separate_counters() -> None:
    """Two sessions hitting the same tool don't pool their counts."""
    mw = ToolCallCountCapMiddleware(per_tool_caps={"inspect_model": 2})
    # Session A — 2 calls, exhausts.
    await mw(_turn("inspect_model", session_id="A"), _passthrough_next)
    await mw(_turn("inspect_model", session_id="A"), _passthrough_next)
    # Session B — first call should still be fine.
    result_b = await mw(_turn("inspect_model", session_id="B"), _passthrough_next)
    assert result_b.status == "pending"


# ──────────────────────── LRU eviction ────────────────


@pytest.mark.asyncio
async def test_lru_eviction_drops_oldest_session() -> None:
    """When max_sessions is exceeded, the LRU oldest session's counter
    drops out — same hygiene as LoopDetectionMiddleware. Important for
    long-running FastAPI processes."""
    mw = ToolCallCountCapMiddleware(max_sessions=2)
    await mw(_turn("inspect_model", session_id="A"), _passthrough_next)
    await mw(_turn("inspect_model", session_id="B"), _passthrough_next)
    await mw(_turn("inspect_model", session_id="C"), _passthrough_next)
    # Session A evicted — its counter is gone.
    assert "A" not in mw._counts
    assert "B" in mw._counts
    assert "C" in mw._counts


@pytest.mark.asyncio
async def test_explicit_evict_drops_session_counter() -> None:
    """Operators can call evict() at session-end without waiting for LRU."""
    mw = ToolCallCountCapMiddleware()
    await mw(_turn("inspect_model", session_id="A"), _passthrough_next)
    assert "A" in mw._counts
    mw.evict("A")
    assert "A" not in mw._counts
