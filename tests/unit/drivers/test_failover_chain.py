"""Unit tests for ChatFailoverChain — fallback + non-retryable bail-out."""

from __future__ import annotations

import pytest

from agentix.core.types import Message
from agentix.drivers.base import (
    DriverDescriptor,
    DriverInvalidRequest,
    DriverRateLimited,
    DriverUnavailable,
)
from agentix.drivers.chat import ChatDriver, ChatRequest, ChatResponse
from agentix.drivers.router import ChatFailoverChain, NoDriversAvailable


class _StubProvider:
    def __init__(self, name: str, *, responses: list[object]) -> None:
        self.name = name
        self.default_model = "stub"
        self._responses = list(responses)
        self.calls = 0

    @property
    def descriptor(self) -> DriverDescriptor:
        return DriverDescriptor(name=self.name, kind="model", modality="chat", default_model=self.default_model)

    async def complete(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        if not self._responses:
            raise RuntimeError("stub exhausted")
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        assert isinstance(nxt, ChatResponse)
        return nxt

    async def aclose(self) -> None:
        pass


def _req() -> ChatRequest:
    return ChatRequest(messages=[Message(role="user", content="hi")])


def _ok(content: str = "ok") -> ChatResponse:
    return ChatResponse(content=content, model="stub")


@pytest.mark.asyncio
async def test_router_returns_first_success() -> None:
    a = _StubProvider("a", responses=[_ok("from-a")])
    b = _StubProvider("b", responses=[_ok("from-b")])
    router = ChatFailoverChain([a, b])
    res = await router.complete(_req())
    assert res.content == "from-a"
    assert a.calls == 1
    assert b.calls == 0


@pytest.mark.asyncio
async def test_router_falls_back_on_rate_limit() -> None:
    a = _StubProvider("a", responses=[DriverRateLimited("429", driver="a")])
    b = _StubProvider("b", responses=[_ok("from-b")])
    router = ChatFailoverChain([a, b])
    res = await router.complete(_req())
    assert res.content == "from-b"
    assert a.calls == 1
    assert b.calls == 1


@pytest.mark.asyncio
async def test_router_falls_back_on_unavailable() -> None:
    a = _StubProvider("a", responses=[DriverUnavailable("502", driver="a")])
    b = _StubProvider("b", responses=[_ok("from-b")])
    router = ChatFailoverChain([a, b])
    res = await router.complete(_req())
    assert res.content == "from-b"


@pytest.mark.asyncio
async def test_router_bails_on_invalid_request() -> None:
    # InvalidRequest is not retryable — router surfaces it and does NOT
    # try downstream providers.
    a = _StubProvider("a", responses=[DriverInvalidRequest("bad", driver="a")])
    b = _StubProvider("b", responses=[_ok("from-b")])
    router = ChatFailoverChain([a, b])
    with pytest.raises(DriverInvalidRequest):
        await router.complete(_req())
    assert a.calls == 1
    assert b.calls == 0


@pytest.mark.asyncio
async def test_router_raises_when_everyone_fails() -> None:
    a = _StubProvider("a", responses=[DriverRateLimited("429", driver="a")])
    b = _StubProvider("b", responses=[DriverUnavailable("503", driver="b")])
    router = ChatFailoverChain([a, b])
    with pytest.raises(NoDriversAvailable) as exc:
        await router.complete(_req())
    assert [name for name, _ in exc.value.attempts] == ["a", "b"]


@pytest.mark.asyncio
async def test_router_rejects_empty_provider_list() -> None:
    with pytest.raises(ValueError, match="at least one"):
        ChatFailoverChain([])


@pytest.mark.asyncio
async def test_router_aclose_closes_every_provider() -> None:
    closed: list[str] = []

    class _Closable(_StubProvider):
        async def aclose(self) -> None:
            closed.append(self.name)

    a = _Closable("a", responses=[_ok()])
    b = _Closable("b", responses=[_ok()])
    router = ChatFailoverChain([a, b])
    await router.aclose()
    assert closed == ["a", "b"]


# ─────────────────── ChatDriver-protocol drop-in ───


@pytest.mark.asyncio
async def test_chain_satisfies_chat_driver_protocol() -> None:
    """ChatFailoverChain must be a Protocol-compatible ChatDriver so callers
    can pass it anywhere a single ChatDriver is expected. Static
    isinstance(chain, ChatDriver) check covers the Protocol surface
    (descriptor, name, default_model, complete, aclose)."""
    a = _StubProvider("a", responses=[_ok("from-a")])
    b = _StubProvider("b", responses=[_ok("from-b")])
    chain = ChatFailoverChain([a, b])
    # Protocol attributes present on the chain itself.
    assert isinstance(chain, ChatDriver)
    assert chain.name == "router"
    # default_model proxies to the first provider — important for
    # CostTrackingMiddleware which seeds cost-per-token from this.
    assert chain.default_model == "stub"


def test_router_default_model_proxies_to_primary() -> None:
    """Two providers with different default_models — router exposes the
    primary's. Ensures cost telemetry doesn't accidentally bill against
    the fallback's model when the primary answered."""
    a = _StubProvider("primary", responses=[])
    a.default_model = "claude-haiku"
    b = _StubProvider("fallback", responses=[])
    b.default_model = "gpt-4"
    router = ChatFailoverChain([a, b])
    assert router.default_model == "claude-haiku"


# ─────────────────── failover callback ──


@pytest.mark.asyncio
async def test_router_invokes_failover_callback_on_retryable_error() -> None:
    """When provider A errors with a retryable DriverError + the router has a
    next provider, the on_failover callback fires with (a_name, next_name, exc)
    BEFORE the next provider is tried."""
    captured: list[tuple[str, str, str]] = []

    async def cb(failed: str, next_: str, exc):  # type: ignore[no-untyped-def]
        captured.append((failed, next_, str(exc)[:100]))

    a = _StubProvider("a", responses=[DriverUnavailable("503 backend down", driver="a")])
    b = _StubProvider("b", responses=[_ok("from-b")])
    router = ChatFailoverChain([a, b], on_failover=cb)

    res = await router.complete(_req())
    assert res.content == "from-b"
    # Callback fired exactly once with the (a, b) pair.
    assert len(captured) == 1
    assert captured[0][0] == "a"
    assert captured[0][1] == "b"
    assert "503" in captured[0][2]


@pytest.mark.asyncio
async def test_router_callback_not_fired_on_terminal_failure() -> None:
    """When the LAST provider fails, there's no next provider — the
    callback must NOT fire (it would imply a non-existent fallback).
    The router raises NoDriversAvailable instead."""
    captured: list[tuple[str, str]] = []

    async def cb(failed, next_, exc):  # type: ignore[no-untyped-def]
        captured.append((failed, next_))

    a = _StubProvider("a", responses=[DriverUnavailable("503", driver="a")])
    b = _StubProvider("b", responses=[DriverUnavailable("503", driver="b")])
    router = ChatFailoverChain([a, b], on_failover=cb)

    with pytest.raises(NoDriversAvailable):
        await router.complete(_req())
    # First failure → callback (a → b). Second failure → no next → no callback.
    assert len(captured) == 1
    assert captured[0] == ("a", "b")


@pytest.mark.asyncio
async def test_router_callback_failure_does_not_propagate() -> None:
    """A buggy callback raising an exception must NOT take down the
    dispatch — best-effort, log + continue. Failover semantics are
    architectural; the callback is observability."""

    async def bad_cb(failed, next_, exc):  # type: ignore[no-untyped-def]
        raise RuntimeError("buggy callback")

    a = _StubProvider("a", responses=[DriverUnavailable("503", driver="a")])
    b = _StubProvider("b", responses=[_ok("from-b")])
    router = ChatFailoverChain([a, b], on_failover=bad_cb)
    # Should still succeed — buggy callback is swallowed.
    res = await router.complete(_req())
    assert res.content == "from-b"


@pytest.mark.asyncio
async def test_router_set_failover_callback_after_construction() -> None:
    """A caller builds the router with no callback (no session id yet);
    the runner attaches a session-aware callback via
    set_failover_callback after creating the session. Validate that
    pattern works."""
    captured: list[tuple[str, str]] = []

    async def cb(failed, next_, exc):  # type: ignore[no-untyped-def]
        captured.append((failed, next_))

    a = _StubProvider("a", responses=[DriverUnavailable("503", driver="a")])
    b = _StubProvider("b", responses=[_ok("from-b")])
    router = ChatFailoverChain([a, b])  # no callback at construction
    router.set_failover_callback(cb)  # attached later
    await router.complete(_req())
    assert captured == [("a", "b")]
