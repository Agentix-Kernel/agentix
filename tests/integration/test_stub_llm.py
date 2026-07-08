"""Unit tests for the stub LLM providers (#204 follow-up to PR #243).

Pin the contract for the two stub flavours:

* ScriptedLLMProvider — pre-canned response queue.
* CallbackLLMProvider — test-supplied response function.

Plus the helper builders for constructing canned responses.
"""

from __future__ import annotations

import pytest

from agentix.core.types import Message
from agentix.drivers.chat import ChatRequest
from tests.integration.stub_llm import (
    CallbackLLMProvider,
    ScriptedLLMProvider,
    StubLLMExhausted,
    final_response,
    tool_call_response,
)


def _request() -> ChatRequest:
    return ChatRequest(
        messages=[Message(role="user", content="go")],
        model="stub-llm",
    )


# ───────────────────── helper builders ─────────────────────


def test_tool_call_response_builds_with_one_call() -> None:
    r = tool_call_response("extract_from_odoo", {"model": "x.y"})
    assert len(r.tool_calls) == 1
    assert r.tool_calls[0].name == "extract_from_odoo"
    assert r.tool_calls[0].arguments == {"model": "x.y"}
    assert r.usage.input_tokens > 0


def test_tool_call_response_supports_multiple_parallel_calls() -> None:
    extra = [tool_call_response("read_file", {"path": "/a"}).tool_calls[0]]
    r = tool_call_response("read_file", {"path": "/b"}, extra_tool_calls=extra)
    assert len(r.tool_calls) == 2
    assert {c.name for c in r.tool_calls} == {"read_file"}


def test_final_response_has_no_tool_calls() -> None:
    r = final_response("MIGRATED: 30 records loaded")
    assert r.tool_calls == []
    assert r.content == "MIGRATED: 30 records loaded"


# ───────────────────── ScriptedLLMProvider ─────────────────────


def test_scripted_requires_at_least_one_response() -> None:
    with pytest.raises(ValueError, match="at least one"):
        ScriptedLLMProvider(responses=[])


@pytest.mark.asyncio
async def test_scripted_pops_responses_in_order() -> None:
    provider = ScriptedLLMProvider(
        responses=[
            tool_call_response("extract_from_odoo", {"model": "x"}),
            tool_call_response("load_to_odoo", {"model": "x"}),
            final_response("MIGRATED"),
        ],
    )
    r1 = await provider.complete(_request())
    r2 = await provider.complete(_request())
    r3 = await provider.complete(_request())
    assert r1.tool_calls[0].name == "extract_from_odoo"
    assert r2.tool_calls[0].name == "load_to_odoo"
    assert r3.tool_calls == []
    assert provider.remaining == 0


@pytest.mark.asyncio
async def test_scripted_records_every_request_for_assertions() -> None:
    """Tests need to inspect the request the agent sent — its
    conversation history is the signal that the previous response's
    tool actually got executed by the dispatcher."""
    provider = ScriptedLLMProvider(responses=[final_response()])
    req = _request()
    await provider.complete(req)
    assert provider.requests == [req]


@pytest.mark.asyncio
async def test_scripted_exhaustion_raises_clearly() -> None:
    provider = ScriptedLLMProvider(responses=[final_response()])
    await provider.complete(_request())  # consumes the only response
    with pytest.raises(StubLLMExhausted, match="exhausted after 2 call"):
        await provider.complete(_request())


# ───────────────────── CallbackLLMProvider ─────────────────────


@pytest.mark.asyncio
async def test_callback_invokes_function_with_request() -> None:
    seen: list[ChatRequest] = []

    def script(request: ChatRequest) -> object:
        seen.append(request)
        return final_response()

    provider = CallbackLLMProvider(callback=script)  # type: ignore[arg-type]
    req = _request()
    await provider.complete(req)
    assert seen == [req]


@pytest.mark.asyncio
async def test_callback_can_branch_on_message_history() -> None:
    """The headline use case: callback inspects the conversation
    history and emits a different response based on what the previous
    tool returned. Pin this contract — adaptive scenarios depend on it."""

    def script(request: ChatRequest):
        # Look for the most recent tool message.
        last_tool = next(
            (m for m in reversed(request.messages) if m.role == "tool"),
            None,
        )
        if last_tool is None:
            # First call: invoke a tool.
            return tool_call_response("extract_from_odoo", {"model": "x.y"})
        # Subsequent call: terminate.
        return final_response("MIGRATED")

    provider = CallbackLLMProvider(callback=script)
    # First call (no tool history) → tool call.
    r1 = await provider.complete(ChatRequest(messages=[Message(role="user", content="go")], model="x"))
    assert r1.tool_calls[0].name == "extract_from_odoo"
    # Second call (tool result in history) → terminate.
    r2 = await provider.complete(
        ChatRequest(
            messages=[
                Message(role="user", content="go"),
                Message(role="assistant", tool_calls=[r1.tool_calls[0]]),
                Message(role="tool", content="ok", tool_call_id=r1.tool_calls[0].id),
            ],
            model="x",
        )
    )
    assert r2.tool_calls == []
