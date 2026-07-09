"""Chat wire types re-home — identity of shim aliases, ChatDriver protocol."""

from __future__ import annotations

import pytest

from agentix.drivers import ChatDriver, ChatRequest, ChatResponse, Driver, DriverDescriptor
from agentix.drivers.chat import tool_to_spec


def test_chat_request_defaults_preserved() -> None:
    req = ChatRequest(messages=[])
    assert req.max_tokens == 16_384
    assert req.temperature == 1.0
    assert req.thinking_enabled is False
    assert req.tools is None
    assert req.tool_choice is None


class _FakeChatDriver:
    name = "fake"
    default_model = "fake-1"

    def __init__(self) -> None:
        self._descriptor = DriverDescriptor(name="fake", type="model", modality="chat", default_model="fake-1")

    @property
    def descriptor(self) -> DriverDescriptor:
        return self._descriptor

    async def complete(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(content="ok", model="fake-1")

    async def aclose(self) -> None:
        pass


def test_chat_driver_protocol_conformance() -> None:
    fake = _FakeChatDriver()
    assert isinstance(fake, ChatDriver)
    assert isinstance(fake, Driver)


def test_tool_to_spec_requires_pydantic_schema() -> None:
    class _NoSchema:
        name = "t"

    with pytest.raises(TypeError, match="input_schema"):
        tool_to_spec(_NoSchema())
