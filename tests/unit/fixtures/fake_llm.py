"""Test doubles used by PR-4 middleware tests.

No real LLM call — everything here is deterministic so ordering + budget
tests stay reproducible.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from agentix.core.types import Message, ToolCallResult, Turn


@dataclass
class FakeReply:
    """What the FakeLLMDispatcher pretends the LLM returned this turn."""

    content: str = "ok"
    input_tokens: int = 100
    output_tokens: int = 50
    cached_tokens: int = 0
    raise_error: Exception | None = None


@dataclass
class FakeLLMDispatcher:
    """Inner-dispatch stand-in for PR-4 tests.

    Emits one ``FakeReply`` per call, cycling through the queue. Each
    reply populates ``turn.assistant_message`` and ``turn.usage`` so
    the functional middlewares have real data to work with.
    """

    replies: Iterable[FakeReply] = field(default_factory=lambda: [FakeReply()])
    calls: int = 0
    _iter: Iterator[FakeReply] | None = None

    async def __call__(self, turn: Turn) -> Turn:
        self.calls += 1
        if self._iter is None:
            self._iter = iter(self.replies)
        try:
            reply = next(self._iter)
        except StopIteration:
            reply = FakeReply()
        if reply.raise_error is not None:
            raise reply.raise_error
        turn.assistant_message = Message(role="assistant", content=reply.content)
        turn.usage.input_tokens = reply.input_tokens
        turn.usage.output_tokens = reply.output_tokens
        turn.usage.cached_tokens = reply.cached_tokens
        return turn


@dataclass
class RecordingMiddleware:
    """Records the order in which middlewares see a turn, before and after."""

    tag: str
    events: list[str]
    name: str = ""

    def __post_init__(self) -> None:
        self.name = self.tag

    async def __call__(self, turn: Turn, next_):  # type: ignore[no-untyped-def]
        self.events.append(f"{self.tag}:before")
        result = await next_(turn)
        self.events.append(f"{self.tag}:after")
        return result


def tool_result(call_id: str = "c1", name: str = "noop", ok: bool = True, output: object = None) -> ToolCallResult:
    return ToolCallResult(call_id=call_id, tool_name=name, ok=ok, output=output)
