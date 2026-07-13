"""Unit tests for HubleChatDriver — request mapping + response parsing."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from agentix.core.types import Message, ToolCall
from agentix.drivers.adapters.intrinsic.huble import (
    HubleChatDriver,
    _message_to_huble,
    _parse_huble_response,
    _split_system,
)
from agentix.drivers.base import (
    DriverInvalidRequest,
    DriverRateLimited,
    DriverUnavailable,
)
from agentix.drivers.chat import ChatRequest, ToolSpec

# ──────────────────────── helper construction ──────────────────────────────


def _provider(transport: httpx.MockTransport, **kw: Any) -> HubleChatDriver:
    """Build a HubleChatDriver whose httpx client uses the supplied mock transport."""
    kw.setdefault("model", "deepseek-v4-flash")
    p = HubleChatDriver(
        base_url="http://huble.test",
        api_key="ludo_test_key",
        **kw,
    )
    # Replace the http client so the unit test never hits the real network.
    p._client = httpx.AsyncClient(
        base_url="http://huble.test",
        headers={"X-API-Key": "ludo_test_key", "Content-Type": "application/json"},
        timeout=10.0,
        transport=transport,
    )
    return p


# ──────────────────────── construction errors ──────────────────────────────


def test_provider_requires_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """``model`` is required by design. The prior optional default
    (``"deepseek-v3.2"``) caused a two-day misdirection — ad-hoc
    callers silently pointed at a model melious no longer served and
    the 500s looked like HUBLE infrastructure problems. Construction
    without a model must now fail loudly."""
    monkeypatch.setenv("LLMHUB_API_KEY", "k")
    with pytest.raises(DriverInvalidRequest, match="model is required"):
        HubleChatDriver(base_url="http://huble.test", model="")


def test_provider_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without LLMHUB_API_KEY env or explicit api_key, init must fail loudly."""
    monkeypatch.delenv("LLMHUB_API_KEY", raising=False)
    with pytest.raises(DriverInvalidRequest, match="LLMHUB_API_KEY"):
        HubleChatDriver(base_url="http://huble.test", model="deepseek-v4-flash")


def test_provider_picks_up_env_url_and_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLMHUB_URL", "http://envhost:4000")
    monkeypatch.setenv("LLMHUB_API_KEY", "envkey")
    p = HubleChatDriver(model="deepseek-v4-flash")
    assert p._base_url == "http://envhost:4000"
    assert p._api_key == "envkey"
    assert p.default_model == "deepseek-v4-flash"


# ──────────────────────── message translation ──────────────────────────────


def test_split_system_pulls_system_prompt() -> None:
    msgs = [
        Message(role="system", content="be ludo"),
        Message(role="system", content="be terse"),
        Message(role="user", content="hi"),
        Message(role="assistant", content="hello"),
    ]
    system, turns = _split_system(msgs)
    assert system == "be ludo\n\nbe terse"
    assert [t["role"] for t in turns] == ["user", "assistant"]


def test_message_to_huble_plain_text() -> None:
    out = _message_to_huble(Message(role="user", content="hi"))
    assert out == {"role": "user", "content": "hi"}


def test_message_to_huble_tool_use_block_for_assistant() -> None:
    msg = Message(
        role="assistant",
        content="calling weather",
        tool_calls=[ToolCall(id="t1", name="get_weather", arguments={"city": "Paris"})],
    )
    out = _message_to_huble(msg)
    assert out["role"] == "assistant"
    blocks = out["content"]
    assert blocks[0] == {"type": "text", "text": "calling weather"}
    assert blocks[1] == {
        "type": "tool_use",
        "id": "t1",
        "name": "get_weather",
        "input": {"city": "Paris"},
    }


def test_message_to_huble_tool_result_becomes_user_role() -> None:
    """Anthropic-shape: tool results go on a synthetic ``user`` turn."""
    msg = Message(role="tool", tool_call_id="t1", content="sunny, 22C")
    out = _message_to_huble(msg)
    assert out == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "sunny, 22C"}],
    }


# ──────────────────────── response parsing ─────────────────────────────────


def test_parse_response_text_only() -> None:
    body = {
        "success": True,
        "content": [{"type": "text", "text": "pong"}],
        "stop_reason": "end_turn",
        "input_tokens": 10,
        "output_tokens": 5,
        "model_used": "deepseek-v3.2",
        "provider_used": "melious",
    }
    resp = _parse_huble_response(body, "deepseek-v3.2")
    assert resp.content == "pong"
    assert resp.tool_calls == []
    assert resp.usage.input_tokens == 10
    assert resp.usage.output_tokens == 5
    assert resp.finish_reason == "end_turn"
    assert resp.raw["provider_used"] == "melious"


def test_parse_response_anthropic_shape_tool_use() -> None:
    """HUBLE returns Anthropic-shape ``content`` with ``tool_use`` blocks
    regardless of upstream — this is the canonical path from the live
    smoke test."""
    body = {
        "success": True,
        "content": [
            {"type": "text", "text": "Looking up weather"},
            {
                "type": "tool_use",
                "id": "abc",
                "name": "get_weather",
                "input": {"city": "Paris"},
            },
        ],
        "stop_reason": "tool_use",
        "input_tokens": 30,
        "output_tokens": 12,
    }
    resp = _parse_huble_response(body, "deepseek-v3.2")
    assert resp.content == "Looking up weather"
    assert len(resp.tool_calls) == 1
    tc = resp.tool_calls[0]
    assert tc.id == "abc"
    assert tc.name == "get_weather"
    assert tc.arguments == {"city": "Paris"}
    assert resp.finish_reason == "tool_use"


def test_parse_response_openai_shape_fallback() -> None:
    """Some upstreams come back via the OpenAI shape (top-level
    ``tool_calls`` array). The provider must accept either."""
    body = {
        "success": True,
        "content": "",
        "tool_calls": [
            {
                "id": "openai_id",
                "function": {
                    "name": "lookup_user",
                    "arguments": '{"user_id": 42}',  # JSON string per OpenAI
                },
            }
        ],
        "stop_reason": "tool_calls",
        "input_tokens": 5,
        "output_tokens": 3,
    }
    resp = _parse_huble_response(body, "gpt-4o")
    assert len(resp.tool_calls) == 1
    tc = resp.tool_calls[0]
    assert tc.name == "lookup_user"
    assert tc.arguments == {"user_id": 42}


def test_parse_response_string_content() -> None:
    """Some non-tool flows come back with a plain string ``content``."""
    body = {
        "success": True,
        "content": "Hello, how are you?",
        "input_tokens": 5,
        "output_tokens": 8,
    }
    resp = _parse_huble_response(body, "deepseek-v3.2")
    assert resp.content == "Hello, how are you?"
    assert resp.tool_calls == []


# ──────────────────────── live wire — full round-trip ──────────────────────


@pytest.mark.asyncio
async def test_complete_sends_messages_and_parses_response() -> None:
    """End-to-end: ChatRequest → HUBLE payload → mock response → ChatResponse.

    Verifies the wire shape we send matches the one the live HUBLE
    smoke test uses (Anthropic-shape: ``messages`` list, separate
    ``system`` field, ``tools`` array)."""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "success": True,
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "input_tokens": 7,
                "output_tokens": 1,
                "model_used": "deepseek-v3.2",
                "provider_used": "melious",
                "log_id": "log-1",
                "cost_usd": 0.000015,
            },
        )

    p = _provider(httpx.MockTransport(handler), upstream_provider="melious", model="deepseek-v3.2")
    req = ChatRequest(
        messages=[
            Message(role="system", content="be ludo"),
            Message(role="user", content="hi"),
        ],
        max_tokens=200,
    )
    resp = await p.complete(req)
    await p.aclose()

    # URL + auth wired correctly.
    assert captured["url"].endswith("/api/v2/agent/chat")
    assert captured["headers"]["x-api-key"] == "ludo_test_key"

    # Payload matches the locked design.
    body = captured["body"]
    assert body["provider"] == "melious"
    assert body["model"] == "deepseek-v3.2"
    assert body["max_tokens"] == 200
    assert body["system"] == "be ludo"
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert "tools" not in body
    assert "tool_choice" not in body

    # Response decoded correctly.
    assert resp.content == "ok"
    assert resp.usage.input_tokens == 7
    assert resp.usage.output_tokens == 1
    assert resp.raw["log_id"] == "log-1"
    assert resp.raw["cost_usd"] == 0.000015


@pytest.mark.asyncio
async def test_complete_forwards_tools_and_tool_choice() -> None:
    """When the agent has a tool catalogue, the provider forwards it."""

    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "success": True,
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "noop", "input": {}},
                ],
                "stop_reason": "tool_use",
                "input_tokens": 5,
                "output_tokens": 2,
            },
        )

    p = _provider(httpx.MockTransport(handler))
    req = ChatRequest(
        messages=[Message(role="user", content="run noop")],
        tools=[
            ToolSpec(
                name="noop",
                description="does nothing",
                input_schema={"type": "object", "properties": {}},
            )
        ],
        tool_choice="auto",
    )
    resp = await p.complete(req)
    await p.aclose()

    body = captured["body"]
    assert body["tools"] == [
        {
            "name": "noop",
            "description": "does nothing",
            "input_schema": {"type": "object", "properties": {}},
        }
    ]
    assert body["tool_choice"] == "auto"
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "noop"


@pytest.mark.asyncio
async def test_complete_429_becomes_rate_limit() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"detail": "Rate limit exceeded"})

    p = _provider(httpx.MockTransport(handler))
    with pytest.raises(DriverRateLimited, match="429"):
        await p.complete(ChatRequest(messages=[Message(role="user", content="x")]))
    await p.aclose()


@pytest.mark.asyncio
async def test_complete_5xx_becomes_unavailable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "service unavailable"})

    p = _provider(httpx.MockTransport(handler))
    with pytest.raises(DriverUnavailable, match="503"):
        await p.complete(ChatRequest(messages=[Message(role="user", content="x")]))
    await p.aclose()


@pytest.mark.asyncio
async def test_complete_4xx_becomes_invalid_request() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": {"code": "PROVIDER_UNAVAILABLE", "message": "no claude"}})

    p = _provider(httpx.MockTransport(handler))
    with pytest.raises(DriverInvalidRequest, match="PROVIDER_UNAVAILABLE"):
        await p.complete(ChatRequest(messages=[Message(role="user", content="x")]))
    await p.aclose()


@pytest.mark.asyncio
async def test_complete_5xx_with_upstream_400_signature_becomes_invalid_request() -> None:
    """#143 regression: HUBLE wraps upstream 400 (context overflow) as
    a 500. LUDO must detect the canonical signature in the body and
    re-classify as DriverInvalidRequest (no-retry) so we don't burn 3
    retries on a fundamentally non-retriable error.
    """

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            json={
                "detail": (
                    "Error code: 400 — This conversation (351,339 tokens) exceeds the model's context window (164,000)"
                )
            },
        )

    p = _provider(httpx.MockTransport(handler))
    with pytest.raises(DriverInvalidRequest, match="HUBLE wrapped upstream 4xx as 5xx"):
        await p.complete(ChatRequest(messages=[Message(role="user", content="x")]))
    await p.aclose()


@pytest.mark.asyncio
async def test_complete_5xx_without_4xx_signature_stays_unavailable() -> None:
    """Genuine HUBLE-side 5xx (no upstream-4xx body signature) keeps
    the existing retry behavior — defence-in-depth must not reclassify
    real outages as invalid requests."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "HUBLE database connection lost"})

    p = _provider(httpx.MockTransport(handler))
    with pytest.raises(DriverUnavailable, match="503"):
        await p.complete(ChatRequest(messages=[Message(role="user", content="x")]))
    await p.aclose()


@pytest.mark.asyncio
async def test_complete_connection_error_becomes_unavailable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    p = _provider(httpx.MockTransport(handler))
    with pytest.raises(DriverUnavailable, match="unreachable"):
        await p.complete(ChatRequest(messages=[Message(role="user", content="x")]))
    await p.aclose()
