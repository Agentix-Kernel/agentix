"""Unit tests for OpenAI + Groq message conversion."""

from __future__ import annotations

import pytest
from agentix.drivers.adapters.vendor.anthropic import AnthropicChatDriver
from agentix.drivers.adapters.vendor.groq import GroqChatDriver
from agentix.drivers.adapters.vendor.openai import OpenAIChatDriver, _to_openai

from agentix.core.types import Message, ToolCall
from agentix.drivers.base import DriverInvalidRequest


def test_openai_init_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(DriverInvalidRequest, match="no OpenAI API key"):
        OpenAIChatDriver()


def test_openai_init_with_explicit_key() -> None:
    provider = OpenAIChatDriver(api_key="sk-test")
    assert provider.name == "openai"
    assert provider.default_model == "gpt-5"


def test_groq_init_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(DriverInvalidRequest, match="no Groq API key"):
        GroqChatDriver()


def test_groq_init_with_explicit_key() -> None:
    provider = GroqChatDriver(api_key="gsk-test")
    assert provider.name == "groq"
    assert provider.default_model == "moonshotai/kimi-k2"


# ─────────────────────── message translation ──────────────────────────────


def test_to_openai_plain_user() -> None:
    out = _to_openai(Message(role="user", content="hi"))
    assert out == {"role": "user", "content": "hi"}


def test_to_openai_tool_result() -> None:
    msg = Message(role="tool", tool_call_id="abc", content="result")
    out = _to_openai(msg)
    assert out == {"role": "tool", "tool_call_id": "abc", "content": "result"}


def test_to_openai_assistant_with_tool_calls() -> None:
    tc = ToolCall(id="call_1", name="extract_from_odoo", arguments={"model": "res.partner"})
    msg = Message(role="assistant", content="calling", tool_calls=[tc])
    out = _to_openai(msg)
    assert out["role"] == "assistant"
    assert len(out["tool_calls"]) == 1
    assert out["tool_calls"][0]["function"]["name"] == "extract_from_odoo"


def test_to_openai_serialises_tool_call_arguments_to_json_string() -> None:
    """PR-P2: OpenAI's API requires function.arguments as a JSON string,
    not a dict. ``_to_openai`` serialises so callers don't have to."""
    import json

    tc = ToolCall(id="call_1", name="extract_from_odoo", arguments={"model": "res.partner", "batch_size": 50})
    msg = Message(role="assistant", content="calling", tool_calls=[tc])
    out = _to_openai(msg)
    args = out["tool_calls"][0]["function"]["arguments"]
    assert isinstance(args, str)
    assert json.loads(args) == {"model": "res.partner", "batch_size": 50}


# Anthropic import is re-exported to keep the package cohesive; this tiny
# assertion catches import regressions.
def test_anthropic_class_exposed() -> None:
    assert AnthropicChatDriver.name == "anthropic"


# ──────────────────────── OpenAI tool round-trip (PR-P2) ────────────


class _FakeFn:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, id: str, name: str, arguments: str) -> None:
        self.id = id
        self.type = "function"
        self.function = _FakeFn(name, arguments)


class _FakeMessage:
    def __init__(self, content: str | None, tool_calls: list[_FakeToolCall] | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls


class _FakeChoice:
    def __init__(self, message: _FakeMessage, finish_reason: str = "stop") -> None:
        self.message = message
        self.finish_reason = finish_reason


class _FakeUsage:
    prompt_tokens = 10
    completion_tokens = 5
    prompt_tokens_details = None


class _FakeCompletion:
    id = "resp_1"
    model = "gpt-5"

    def __init__(self, choice: _FakeChoice) -> None:
        self.choices = [choice]
        self.usage = _FakeUsage()


class _FakeCompletionsClient:
    def __init__(self, response: _FakeCompletion) -> None:
        self.kwargs: dict[str, object] = {}
        self._response = response

    async def create(self, **kwargs: object) -> _FakeCompletion:
        self.kwargs = kwargs
        return self._response

    async def close(self) -> None:
        return None


class _FakeChatClient:
    def __init__(self, response: _FakeCompletion) -> None:
        self.completions = _FakeCompletionsClient(response)


class _FakeOpenAIClient:
    def __init__(self, response: _FakeCompletion) -> None:
        self.chat = _FakeChatClient(response)

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_openai_sends_tools_with_function_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PR-P2: ChatRequest.tools → ``[{"type":"function","function":...}]``."""
    from agentix.drivers.chat import ChatRequest, ToolSpec

    provider = OpenAIChatDriver(api_key="sk-test")
    fake = _FakeOpenAIClient(_FakeCompletion(_FakeChoice(_FakeMessage("hi"))))
    monkeypatch.setattr(provider, "_client", fake)

    spec = ToolSpec(
        name="extract_from_odoo",
        description="Extract records.",
        input_schema={"type": "object", "properties": {"model": {"type": "string"}}},
    )
    await provider.complete(
        ChatRequest(messages=[Message(role="user", content="run")], tools=[spec], tool_choice="any")
    )

    sent = fake.chat.completions.kwargs.get("tools")
    assert isinstance(sent, list) and len(sent) == 1
    assert sent[0]["type"] == "function"
    assert sent[0]["function"]["name"] == "extract_from_odoo"
    assert sent[0]["function"]["parameters"]["type"] == "object"
    # tool_choice "any" maps to OpenAI's "required".
    assert fake.chat.completions.kwargs["tool_choice"] == "required"


@pytest.mark.asyncio
async def test_openai_parses_tool_calls_from_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PR-P2: ``choice.message.tool_calls`` → ChatResponse.tool_calls with
    JSON-decoded arguments."""
    import json

    from agentix.drivers.chat import ChatRequest

    provider = OpenAIChatDriver(api_key="sk-test")
    tc = _FakeToolCall(
        id="call_1",
        name="extract_from_odoo",
        arguments=json.dumps({"model": "res.partner", "batch_size": 50}),
    )
    msg = _FakeMessage(content=None, tool_calls=[tc])
    fake = _FakeOpenAIClient(_FakeCompletion(_FakeChoice(msg, finish_reason="tool_calls")))
    monkeypatch.setattr(provider, "_client", fake)

    resp = await provider.complete(ChatRequest(messages=[Message(role="user", content="go")]))
    assert resp.finish_reason == "tool_calls"
    assert len(resp.tool_calls) == 1
    call = resp.tool_calls[0]
    assert call.id == "call_1"
    assert call.name == "extract_from_odoo"
    assert call.arguments == {"model": "res.partner", "batch_size": 50}


@pytest.mark.asyncio
async def test_openai_malformed_tool_arguments_surface_visibly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Broken JSON from the model must not silently become empty args —
    preserve the raw string under a sentinel key so the dispatcher can
    re-prompt with the actual error."""
    from agentix.drivers.chat import ChatRequest

    provider = OpenAIChatDriver(api_key="sk-test")
    tc = _FakeToolCall(id="call_x", name="extract_from_odoo", arguments="{malformed:")
    msg = _FakeMessage(content=None, tool_calls=[tc])
    fake = _FakeOpenAIClient(_FakeCompletion(_FakeChoice(msg, finish_reason="tool_calls")))
    monkeypatch.setattr(provider, "_client", fake)

    resp = await provider.complete(ChatRequest(messages=[Message(role="user", content="go")]))
    assert resp.tool_calls[0].arguments == {"_malformed": "{malformed:"}


# ──────────────────────── Groq tool round-trip (PR-P2) ──────────────


class _FakeGroqChatClient:
    def __init__(self, response: _FakeCompletion) -> None:
        self.completions = _FakeCompletionsClient(response)


class _FakeGroqClient:
    def __init__(self, response: _FakeCompletion) -> None:
        self.chat = _FakeGroqChatClient(response)

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_groq_sends_tools_via_openai_compatible_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agentix.drivers.chat import ChatRequest, ToolSpec

    provider = GroqChatDriver(api_key="gsk-test")
    fake = _FakeGroqClient(_FakeCompletion(_FakeChoice(_FakeMessage("hi"))))
    monkeypatch.setattr(provider, "_client", fake)

    await provider.complete(
        ChatRequest(
            messages=[Message(role="user", content="go")],
            tools=[ToolSpec(name="t", description="", input_schema={"type": "object"})],
            tool_choice="auto",
        )
    )
    sent = fake.chat.completions.kwargs.get("tools")
    assert isinstance(sent, list) and sent[0]["type"] == "function"
    assert fake.chat.completions.kwargs["tool_choice"] == "auto"


@pytest.mark.asyncio
async def test_groq_parses_tool_calls_from_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    from agentix.drivers.chat import ChatRequest

    provider = GroqChatDriver(api_key="gsk-test")
    tc = _FakeToolCall(id="call_g", name="inspect_model", arguments=json.dumps({"model": "res.partner"}))
    msg = _FakeMessage(content=None, tool_calls=[tc])
    fake = _FakeGroqClient(_FakeCompletion(_FakeChoice(msg, finish_reason="tool_calls")))
    monkeypatch.setattr(provider, "_client", fake)

    resp = await provider.complete(ChatRequest(messages=[Message(role="user", content="go")]))
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "inspect_model"
    assert resp.tool_calls[0].arguments == {"model": "res.partner"}
