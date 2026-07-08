"""Reusable stub LLM providers for agent-path integration tests.

Two flavours:

* :class:`ScriptedLLMProvider` — pre-canned response queue. Each
  ``complete()`` call pops the next response. Use when the agent's
  flow is deterministic and you want maximum control.

* :class:`CallbackLLMProvider` — every ``complete()`` invokes a
  test-supplied callback ``(request) -> ChatResponse``. The callback
  inspects the request (last tool result, full message history) and
  returns the appropriate next response. Use for adaptive scenarios
  (agent's behaviour depends on what the previous tool returned).

Both implement the :class:`Provider` protocol so the agent runner
uses them as drop-in replacements for HUBLE / Anthropic.

Helper builders make it cheap to write canned responses without
hand-constructing pydantic models:

* :func:`tool_call_response` — single tool call with arguments.
* :func:`final_response` — terminal message (no tool_calls).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import structlog

from agentix.core.types import TokenUsage, ToolCall
from agentix.drivers.chat import ChatRequest, ChatResponse

log = structlog.get_logger(__name__)


# ───────────────────── helper builders ─────────────────────


def tool_call_response(
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    *,
    content: str = "",
    model: str = "stub-llm",
    input_tokens: int = 100,
    output_tokens: int = 50,
    call_id: str | None = None,
    extra_tool_calls: list[ToolCall] | None = None,
) -> ChatResponse:
    """Build an ChatResponse that tells the agent to invoke ``tool_name``
    with ``arguments``. Optionally include extra tool calls for
    parallel-tool scenarios."""
    calls = [
        ToolCall(
            id=call_id or f"call_{uuid.uuid4().hex[:12]}",
            name=tool_name,
            arguments=arguments or {},
        ),
    ]
    if extra_tool_calls:
        calls.extend(extra_tool_calls)
    return ChatResponse(
        content=content,
        model=model,
        usage=TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens),
        tool_calls=calls,
    )


def final_response(
    content: str = "MIGRATED",
    *,
    model: str = "stub-llm",
    input_tokens: int = 50,
    output_tokens: int = 20,
) -> ChatResponse:
    """Build a terminal response — no tool_calls — that ends the agent
    loop. Use for the last response in a scripted sequence."""
    return ChatResponse(
        content=content,
        model=model,
        usage=TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens),
        tool_calls=[],
    )


# ───────────────────── ScriptedLLMProvider ─────────────────────


class StubLLMExhausted(RuntimeError):
    """Raised when a ScriptedLLMProvider runs out of pre-canned responses."""


class ScriptedLLMProvider:
    """Pops the next response from a queue on every ``complete()`` call.

    Construct with a list of responses (use the helper builders to
    keep tests readable). Records every request for assertion.

    Use case: deterministic agent flows where you know exactly what
    tool calls the agent should make in what order.

    Example:

        provider = ScriptedLLMProvider(responses=[
            tool_call_response("extract_from_odoo", {"model": "x.y"}),
            tool_call_response("load_to_odoo", {"model": "x.y", "id_columns": ["id"]}),
            final_response("MIGRATED"),
        ])
    """

    name = "stub-scripted"

    def __init__(self, *, responses: list[ChatResponse]) -> None:
        if not responses:
            raise ValueError("ScriptedLLMProvider needs at least one response")
        self._responses = list(responses)
        self.default_model = responses[0].model
        self.requests: list[ChatRequest] = []

    async def complete(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        if not self._responses:
            raise StubLLMExhausted(
                f"ScriptedLLMProvider exhausted after {len(self.requests)} call(s); "
                f"add another response to the queue or end with final_response()"
            )
        return self._responses.pop(0)

    async def aclose(self) -> None:
        return None

    @property
    def remaining(self) -> int:
        return len(self._responses)


# ───────────────────── CallbackLLMProvider ─────────────────────


class CallbackLLMProvider:
    """Defers each ``complete()`` decision to a test-supplied callback.

    The callback receives the full ``ChatRequest`` (including the
    conversation history with tool results) and returns the next
    ``ChatResponse``. This lets adaptive tests inspect what tools
    returned and emit the right next call.

    Example:

        async def script(request: ChatRequest) -> ChatResponse:
            last_tool_result = next(
                (m for m in reversed(request.messages) if m.role == "tool"),
                None,
            )
            if last_tool_result and "Invalid field" in (last_tool_result.content or ""):
                return tool_call_response("update_rename_map", {...})
            return final_response("MIGRATED")

        provider = CallbackLLMProvider(callback=script)
    """

    name = "stub-callback"

    def __init__(
        self,
        *,
        callback: Callable[[ChatRequest], ChatResponse],
        default_model: str = "stub-llm",
    ) -> None:
        self._callback = callback
        self.default_model = default_model
        self.requests: list[ChatRequest] = []

    async def complete(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        result = self._callback(request)
        return result

    async def aclose(self) -> None:
        return None
