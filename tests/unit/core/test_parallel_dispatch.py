"""Unit tests for parallel read-only tool dispatch (#95).

Verifies that AgentDispatcher runs consecutive mutates_target=False tool calls
concurrently, keeps result ordering, and falls back to sequential for writes
or when parallel_reads=False.

The dispatcher is exercised by calling _dispatch_tool_calls directly — no real
LLM or SQLite needed; stubs cover the safety gate, persistence, and tool ctx.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from agentix.core.agent_dispatcher import AgentDispatcher
from agentix.core.types import ToolCall, Turn
from agentix.tools.base import Tool, ToolContext
from agentix.tools.registry import ToolRegistry
from agentix.tools.safety import SafetyGate

# ── minimal stubs ──────────────────────────────────────────────────────────


def _make_tool(name: str, *, mutates: bool = False) -> Tool:
    """Stub tool that records calls and returns ok=True."""
    t = MagicMock(spec=Tool)
    t.name = name
    t.mutates_target = mutates
    t.advertised = True
    t.default_timeout_seconds = 30.0
    t.input_schema = MagicMock()
    t.input_schema.model_fields = {}
    t.input_schema.model_validate = MagicMock(return_value=MagicMock())
    # registry.register checks verifier presence for mutating tools
    t.verifier = MagicMock() if mutates else None
    return t


def _registry(*tools: Tool) -> ToolRegistry:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    return reg


def _turn(session_id: str = "s1") -> Turn:
    return Turn(session_id=session_id, turn_index=0, input_messages=[])


def _call(tool_name: str, call_id: str | None = None) -> ToolCall:
    return ToolCall(
        id=call_id or f"c_{tool_name}",
        name=tool_name,
        arguments={},
    )


class _NullGate(SafetyGate):
    """Safety gate that always permits and returns a simple output dict."""

    def __init__(self) -> None:
        super().__init__(sqlite=MagicMock())

    async def execute(self, tool: Tool, input_model: Any, ctx: ToolContext) -> Any:
        out = MagicMock()
        out.model_dump = MagicMock(return_value={"tool": tool.name})
        return out


def _dispatcher(
    *tools: Tool,
    parallel_reads: bool = True,
) -> AgentDispatcher:
    reg = _registry(*tools)
    gate = _NullGate()
    ctx_factory = MagicMock(return_value=MagicMock(spec=ToolContext))

    d = AgentDispatcher(
        driver=MagicMock(),
        registry=reg,
        safety_gate=gate,
        ctx_factory=ctx_factory,
        parallel_reads=parallel_reads,
    )
    # Stub out persistence so tests are self-contained.
    d._persist_iteration = AsyncMock()
    return d


def _ctx() -> ToolContext:
    ctx = MagicMock(spec=ToolContext)
    ctx.session = MagicMock()
    ctx.session.working_memory = MagicMock()
    ctx.session.working_memory.attempts = []
    ctx.session.working_memory.blocked_paths = []
    ctx.session.working_memory.record = MagicMock()
    ctx.session.working_memory.active_strategy = ""
    ctx.sqlite = MagicMock()
    ctx.minio = MagicMock()
    ctx._current_tool_name = None
    return ctx


# ── concurrency detection ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parallel_reads_overlap_in_time() -> None:
    """Two read-only tools in one response execute concurrently (gate awaits overlap)."""
    started: list[str] = []
    finished: list[str] = []
    barrier = asyncio.Event()

    read_a = _make_tool("read_a")
    read_b = _make_tool("read_b")

    class OverlapGate(SafetyGate):
        def __init__(self) -> None:
            super().__init__(sqlite=MagicMock())

        async def execute(self, tool: Tool, input_model: Any, ctx: ToolContext) -> Any:
            started.append(tool.name)
            if len(started) == 2:
                barrier.set()  # both started → unblock each other
            await barrier.wait()
            finished.append(tool.name)
            out = MagicMock()
            out.model_dump = MagicMock(return_value={})
            return out

    reg = _registry(read_a, read_b)
    d = AgentDispatcher(
        driver=MagicMock(),
        registry=reg,
        safety_gate=OverlapGate(),
        ctx_factory=MagicMock(return_value=_ctx()),
        parallel_reads=True,
    )
    d._persist_iteration = AsyncMock()

    turn = _turn()
    aborted = await d._dispatch_tool_calls([_call("read_a"), _call("read_b")], _ctx(), turn)

    assert not aborted
    assert set(started) == {"read_a", "read_b"}
    # Both started before either finished → true overlap
    assert len(started) == 2 and len(finished) == 2


@pytest.mark.asyncio
async def test_parallel_reads_disabled_runs_sequentially() -> None:
    """parallel_reads=False → reads execute one-after-the-other."""
    order: list[str] = []

    class OrderGate(SafetyGate):
        def __init__(self) -> None:
            super().__init__(sqlite=MagicMock())

        async def execute(self, tool: Tool, input_model: Any, ctx: ToolContext) -> Any:
            order.append(tool.name)
            out = MagicMock()
            out.model_dump = MagicMock(return_value={})
            return out

    read_a = _make_tool("read_a")
    read_b = _make_tool("read_b")
    reg = _registry(read_a, read_b)
    d = AgentDispatcher(
        driver=MagicMock(),
        registry=reg,
        safety_gate=OrderGate(),
        ctx_factory=MagicMock(return_value=_ctx()),
        parallel_reads=False,
    )
    d._persist_iteration = AsyncMock()

    turn = _turn()
    await d._dispatch_tool_calls([_call("read_a"), _call("read_b")], _ctx(), turn)
    assert order == ["read_a", "read_b"]


# ── result ordering ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parallel_results_in_original_order() -> None:
    """Parallel execution: transcript order must match tool_calls order."""
    # read_slow finishes after read_fast but must appear first in transcript.
    fast_done = asyncio.Event()

    class LatencyGate(SafetyGate):
        def __init__(self) -> None:
            super().__init__(sqlite=MagicMock())

        async def execute(self, tool: Tool, input_model: Any, ctx: ToolContext) -> Any:
            if tool.name == "read_slow":
                await fast_done.wait()  # wait until fast is done
            else:
                fast_done.set()
            out = MagicMock()
            out.model_dump = MagicMock(return_value={"name": tool.name})
            return out

    slow = _make_tool("read_slow")
    fast = _make_tool("read_fast")
    reg = _registry(slow, fast)
    d = AgentDispatcher(
        driver=MagicMock(),
        registry=reg,
        safety_gate=LatencyGate(),
        ctx_factory=MagicMock(return_value=_ctx()),
        parallel_reads=True,
    )
    d._persist_iteration = AsyncMock()

    turn = _turn()
    ctx = _ctx()
    await d._dispatch_tool_calls([_call("read_slow"), _call("read_fast")], ctx, turn)

    names = [r.tool_name for r in turn.tool_call_results]
    assert names == ["read_slow", "read_fast"], f"got {names}"
    msgs = [m.tool_call_id for m in turn.input_messages if m.role == "tool"]
    assert msgs == ["c_read_slow", "c_read_fast"]


# ── write isolation ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_write_breaks_parallel_run() -> None:
    """read, write, read → two separate sequential dispatches; no cross-group overlap."""
    order: list[str] = []

    class OrderGate(SafetyGate):
        def __init__(self) -> None:
            super().__init__(sqlite=MagicMock())

        async def execute(self, tool: Tool, input_model: Any, ctx: ToolContext) -> Any:
            order.append(tool.name)
            out = MagicMock()
            out.model_dump = MagicMock(return_value={})
            return out

    r1 = _make_tool("r1")
    w1 = _make_tool("w1", mutates=True)
    r2 = _make_tool("r2")
    reg = _registry(r1, w1, r2)
    d = AgentDispatcher(
        driver=MagicMock(),
        registry=reg,
        safety_gate=OrderGate(),
        ctx_factory=MagicMock(return_value=_ctx()),
        parallel_reads=True,
    )
    d._persist_iteration = AsyncMock()

    turn = _turn()
    await d._dispatch_tool_calls([_call("r1"), _call("w1"), _call("r2")], _ctx(), turn)
    # r1 → w1 → r2 must be sequential across the write boundary
    assert order == ["r1", "w1", "r2"]


@pytest.mark.asyncio
async def test_two_reads_then_write_order() -> None:
    """Two concurrent reads followed by a write: reads finish before write starts."""
    order: list[str] = []
    both_started = asyncio.Event()

    class Gate(SafetyGate):
        def __init__(self) -> None:
            super().__init__(sqlite=MagicMock())

        async def execute(self, tool: Tool, input_model: Any, ctx: ToolContext) -> Any:
            order.append(f"start:{tool.name}")
            if tool.name in ("r1", "r2"):
                if sum(1 for e in order if e.startswith("start:r")) == 2:
                    both_started.set()
                await both_started.wait()
            order.append(f"end:{tool.name}")
            out = MagicMock()
            out.model_dump = MagicMock(return_value={})
            return out

    r1 = _make_tool("r1")
    r2 = _make_tool("r2")
    w1 = _make_tool("w1", mutates=True)
    reg = _registry(r1, r2, w1)
    d = AgentDispatcher(
        driver=MagicMock(),
        registry=reg,
        safety_gate=Gate(),
        ctx_factory=MagicMock(return_value=_ctx()),
        parallel_reads=True,
    )
    d._persist_iteration = AsyncMock()

    turn = _turn()
    await d._dispatch_tool_calls([_call("r1"), _call("r2"), _call("w1")], _ctx(), turn)

    # w1 must only start after both reads ended
    w_start = order.index("start:w1")
    r1_end = order.index("end:r1")
    r2_end = order.index("end:r2")
    assert w_start > r1_end and w_start > r2_end
