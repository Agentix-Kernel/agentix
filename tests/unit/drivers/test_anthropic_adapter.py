"""Unit tests for AnthropicChatDriver — message mapping + response parsing.

Token-resolution coverage lives in ``test_anthropic_auth.py`` (the four
TokenSource implementations + the chain resolver).
"""

from __future__ import annotations

from typing import Any

import pytest
from agentix.drivers.adapters.vendor.anthropic import (
    _from_anthropic_response,
    _message_to_anthropic,
    _split_system,
)

from agentix.core.types import Message, ToolCall

# ───────────────────────── message translation ─────────────────────────────


def test_split_system_collects_system_content() -> None:
    msgs = [
        Message(role="system", content="be helpful"),
        Message(role="system", content="and concise"),
        Message(role="user", content="hi"),
    ]
    system, turns = _split_system(msgs)
    assert "be helpful" in system
    assert "and concise" in system
    assert len(turns) == 1
    assert turns[0]["role"] == "user"


def test_message_to_anthropic_plain_user() -> None:
    out = _message_to_anthropic(Message(role="user", content="hello"))
    assert out == {"role": "user", "content": "hello"}


def test_message_to_anthropic_tool_result() -> None:
    msg = Message(role="tool", tool_call_id="abc", content='{"ok":true}')
    out = _message_to_anthropic(msg)
    assert out["role"] == "user"
    assert out["content"][0]["type"] == "tool_result"
    assert out["content"][0]["tool_use_id"] == "abc"


def test_message_to_anthropic_assistant_with_tool_calls() -> None:
    tc = ToolCall(id="t1", name="extract_from_odoo", arguments={"model": "res.partner"})
    msg = Message(role="assistant", content="will extract", tool_calls=[tc])
    out = _message_to_anthropic(msg)
    assert out["role"] == "assistant"
    block_types = [b["type"] for b in out["content"]]
    assert block_types == ["text", "tool_use"]


# ───────────────────────── response parsing ────────────────────────────────


class _FakeBlock:
    def __init__(self, btype: str, text: str = "") -> None:
        self.type = btype
        self.text = text


class _FakeUsage:
    input_tokens = 10
    output_tokens = 5
    cache_read_input_tokens = 2


class _FakeResponse:
    id: str = "resp_123"
    model: str = "claude-sonnet-4-6"
    stop_reason: str = "end_turn"

    def __init__(self) -> None:
        self.content = [_FakeBlock("text", "hi there"), _FakeBlock("thinking")]
        self.usage = _FakeUsage()


def test_from_anthropic_response_collapses_text_blocks() -> None:
    out = _from_anthropic_response(_FakeResponse(), "claude-sonnet-4-6")
    assert out.content == "hi there"  # thinking block skipped
    assert out.usage.input_tokens == 10
    assert out.usage.output_tokens == 5
    assert out.usage.cached_tokens == 2
    assert out.model == "claude-sonnet-4-6"
    assert out.finish_reason == "end_turn"


# ───────────────────────── prompt-caching audit (PR-H) ──────────────────


class _CapturingClient:
    """Minimal async anthropic client that captures the kwargs of messages.create.

    The response type is ``Any`` so tests can inject either a text-only
    ``_FakeResponse`` or a tool-use-carrying ``_FakeToolResponse`` without
    subclass gymnastics.

    ``with_options`` mirrors anthropic.AsyncAnthropic's copy-on-write
    pattern that the real SDK uses for per-request auth_token refresh —
    the test stub records the override but routes ``messages.create``
    back to the original so assertions on ``kwargs`` keep working.
    """

    def __init__(self, response: Any) -> None:
        self.kwargs: dict[str, object] = {}
        self.refreshed_auth_tokens: list[str] = []
        self._response = response
        self.messages = self

    async def create(self, **kwargs: object) -> Any:
        self.kwargs = kwargs
        return self._response

    def with_options(self, *, auth_token: str | None = None, **_: object) -> _CapturingClient:
        if auth_token is not None:
            self.refreshed_auth_tokens.append(auth_token)
        return self

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_cache_control_promotes_system_to_block_with_ephemeral_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When cache_control=True (API-key mode), the system prompt is sent as
    a block list carrying `cache_control: {"type": "ephemeral"}` and the
    prompt-caching beta header is set."""
    from agentix.drivers.adapters.vendor.anthropic import AnthropicChatDriver

    from agentix.drivers.chat import ChatRequest

    provider = AnthropicChatDriver(api_key="sk-ant-api-x", model="claude-sonnet-4-6")
    fake_client = _CapturingClient(_FakeResponse())
    monkeypatch.setattr(provider, "_client", fake_client)

    request = ChatRequest(
        messages=[
            Message(role="system", content="you are ludo"),
            Message(role="user", content="hi"),
        ],
        cache_control=True,
    )
    await provider.complete(request)

    assert isinstance(fake_client.kwargs["system"], list)
    system_blocks = fake_client.kwargs["system"]
    assert isinstance(system_blocks, list) and len(system_blocks) == 1
    block = system_blocks[0]
    assert isinstance(block, dict)
    assert block["type"] == "text"
    assert block["text"] == "you are ludo"
    assert block["cache_control"] == {"type": "ephemeral"}
    headers = fake_client.kwargs.get("extra_headers")
    assert isinstance(headers, dict)
    assert "prompt-caching" in headers.get("anthropic-beta", "")


@pytest.mark.asyncio
async def test_cache_control_off_keeps_system_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: without cache_control, the system prompt is still a plain
    string so we don't send unused extra_headers to the API."""
    from agentix.drivers.adapters.vendor.anthropic import AnthropicChatDriver

    from agentix.drivers.chat import ChatRequest

    provider = AnthropicChatDriver(api_key="sk-ant-api-x", model="claude-sonnet-4-6")
    fake_client = _CapturingClient(_FakeResponse())
    monkeypatch.setattr(provider, "_client", fake_client)

    request = ChatRequest(
        messages=[
            Message(role="system", content="you are ludo"),
            Message(role="user", content="hi"),
        ],
        cache_control=False,
    )
    await provider.complete(request)

    assert fake_client.kwargs["system"] == "you are ludo"
    assert "extra_headers" not in fake_client.kwargs


# ───────────────────────── tool use round-trip (PR-P2) ──────────────


class _FakeToolUseBlock:
    def __init__(self, id: str, name: str, input_: dict[str, object]) -> None:
        self.type = "tool_use"
        self.id = id
        self.name = name
        self.input = input_


class _FakeToolResponse:
    id: str = "resp_tool"
    model: str = "claude-sonnet-4-6"
    stop_reason: str = "tool_use"

    def __init__(self) -> None:
        self.content = [
            _FakeBlock("text", "Calling extract_from_odoo"),
            _FakeToolUseBlock(
                id="tool_1",
                name="extract_from_odoo",
                input_={"model": "res.partner", "batch_size": 50},
            ),
        ]
        self.usage = _FakeUsage()


@pytest.mark.asyncio
async def test_anthropic_sends_tools_in_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """PR-P2: ChatRequest.tools → Anthropic ``tools`` kwarg with
    {name, description, input_schema}."""
    from agentix.drivers.adapters.vendor.anthropic import AnthropicChatDriver

    from agentix.drivers.chat import ChatRequest, ToolSpec

    provider = AnthropicChatDriver(api_key="sk-ant-api-x", model="claude-sonnet-4-6")
    fake_client = _CapturingClient(_FakeResponse())
    monkeypatch.setattr(provider, "_client", fake_client)

    tool = ToolSpec(
        name="extract_from_odoo",
        description="Extract records from Odoo.",
        input_schema={"type": "object", "properties": {"model": {"type": "string"}}},
    )
    await provider.complete(
        ChatRequest(
            messages=[Message(role="user", content="run it")],
            tools=[tool],
            tool_choice="auto",
        )
    )
    assert "tools" in fake_client.kwargs
    sent = fake_client.kwargs["tools"]
    assert isinstance(sent, list) and len(sent) == 1
    assert sent[0]["name"] == "extract_from_odoo"
    assert sent[0]["input_schema"]["type"] == "object"
    assert fake_client.kwargs["tool_choice"] == {"type": "auto"}


@pytest.mark.asyncio
async def test_anthropic_parses_tool_use_response_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """tool_use blocks in the response become ChatResponse.tool_calls."""
    from agentix.drivers.adapters.vendor.anthropic import AnthropicChatDriver

    from agentix.drivers.chat import ChatRequest

    provider = AnthropicChatDriver(api_key="sk-ant-api-x", model="claude-sonnet-4-6")
    fake_client = _CapturingClient(_FakeToolResponse())
    monkeypatch.setattr(provider, "_client", fake_client)

    resp = await provider.complete(ChatRequest(messages=[Message(role="user", content="go")]))
    assert resp.finish_reason == "tool_use"
    assert len(resp.tool_calls) == 1
    call = resp.tool_calls[0]
    assert call.id == "tool_1"
    assert call.name == "extract_from_odoo"
    assert call.arguments == {"model": "res.partner", "batch_size": 50}
    assert resp.content == "Calling extract_from_odoo"


@pytest.mark.asyncio
async def test_anthropic_oauth_downgrades_tool_choice_any_to_auto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OAuth flow disallows forced tool selection — normalise silently."""
    from agentix.drivers.adapters.vendor.anthropic import AnthropicChatDriver

    from agentix.drivers.chat import ChatRequest, ToolSpec

    provider = AnthropicChatDriver(api_key="sk-ant-oat-x", model="claude-sonnet-4-6")
    fake_client = _CapturingClient(_FakeResponse())
    monkeypatch.setattr(provider, "_client", fake_client)

    await provider.complete(
        ChatRequest(
            messages=[Message(role="user", content="go")],
            tools=[ToolSpec(name="t", description="", input_schema={"type": "object"})],
            tool_choice="any",
        )
    )
    assert fake_client.kwargs["tool_choice"] == {"type": "auto"}


@pytest.mark.asyncio
async def test_anthropic_no_tools_means_no_tools_kwarg(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: request without tools → ``tools`` kwarg is not sent."""
    from agentix.drivers.adapters.vendor.anthropic import AnthropicChatDriver

    from agentix.drivers.chat import ChatRequest

    provider = AnthropicChatDriver(api_key="sk-ant-api-x", model="claude-sonnet-4-6")
    fake_client = _CapturingClient(_FakeResponse())
    monkeypatch.setattr(provider, "_client", fake_client)

    await provider.complete(ChatRequest(messages=[Message(role="user", content="hi")]))
    assert "tools" not in fake_client.kwargs
    assert "tool_choice" not in fake_client.kwargs


@pytest.mark.asyncio
async def test_cache_control_noop_under_oauth(monkeypatch: pytest.MonkeyPatch) -> None:
    """OAuth auth rejects prompt caching — the request must NOT carry
    cache_control markers even when the caller asked for them."""
    from agentix.drivers.adapters.vendor.anthropic import AnthropicChatDriver

    from agentix.drivers.chat import ChatRequest

    provider = AnthropicChatDriver(api_key="sk-ant-oat-x", model="claude-sonnet-4-6")
    fake_client = _CapturingClient(_FakeResponse())
    monkeypatch.setattr(provider, "_client", fake_client)

    request = ChatRequest(
        messages=[
            Message(role="system", content="you are ludo"),
            Message(role="user", content="hi"),
        ],
        cache_control=True,  # ignored in OAuth mode
    )
    await provider.complete(request)

    # System stays as string — no cache_control block.
    assert fake_client.kwargs["system"] == "you are ludo"
    # No prompt-caching header.
    headers = fake_client.kwargs.get("extra_headers") or {}
    if isinstance(headers, dict):
        assert "prompt-caching" not in headers.get("anthropic-beta", "")
