"""Unit tests for DriverRegistry — strict/lenient registration, typed lookup."""

from __future__ import annotations

import pytest

from agentix.drivers import ChatRequest, ChatResponse, DriverDescriptor
from agentix.drivers.registry import DriverConflict, DriverRegistry


class _FakeChat:
    name = "fake-chat"
    default_model = "fake-1"

    def __init__(self, name: str = "fake-chat") -> None:
        self.name = name
        self._descriptor = DriverDescriptor(name=name, type="model", modality="chat", default_model="fake-1")
        self.closed = False

    @property
    def descriptor(self) -> DriverDescriptor:
        return self._descriptor

    async def complete(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(content="ok", model="fake-1")

    async def aclose(self) -> None:
        self.closed = True


class _FakeDb:
    def __init__(self) -> None:
        self._descriptor = DriverDescriptor(name="db-main", type="database", source="local")

    @property
    def descriptor(self) -> DriverDescriptor:
        return self._descriptor

    async def aclose(self) -> None:
        pass


def test_register_and_get() -> None:
    reg = DriverRegistry()
    drv = _FakeChat()
    reg.register(drv)
    assert reg.get("fake-chat") is drv
    assert "fake-chat" in reg
    assert len(reg) == 1


def test_register_conflict_raises() -> None:
    reg = DriverRegistry()
    reg.register(_FakeChat())
    with pytest.raises(DriverConflict, match="fake-chat"):
        reg.register(_FakeChat())


def test_register_rejects_descriptorless_object() -> None:
    reg = DriverRegistry()
    with pytest.raises(TypeError, match="DriverDescriptor"):
        reg.register(object())  # type: ignore[arg-type]


def test_try_register_is_lenient() -> None:
    reg = DriverRegistry()
    assert reg.try_register(_FakeChat()) is True
    assert reg.try_register(_FakeChat()) is False  # conflict → skip, no raise
    assert len(reg) == 1


def test_default_per_modality_is_first_registered() -> None:
    reg = DriverRegistry()
    a, b = _FakeChat("chat-a"), _FakeChat("chat-b")
    reg.register(a)
    reg.register(b)
    assert reg.chat() is a
    assert reg.chat("chat-b") is b


def test_default_flag_overrides_insertion_order() -> None:
    reg = DriverRegistry()
    a, b = _FakeChat("chat-a"), _FakeChat("chat-b")
    reg.register(a)
    reg.register(b, default=True)
    assert reg.chat() is b


def test_typed_accessor_type_mismatch() -> None:
    reg = DriverRegistry()
    db = _FakeDb()
    reg.register(db)
    # db-main is not a chat driver; named chat lookup must TypeError.
    with pytest.raises(TypeError, match="not a ChatDriver"):
        reg.chat("db-main")


def test_missing_modality_lookups() -> None:
    reg = DriverRegistry()
    with pytest.raises(KeyError):
        reg.chat()
    with pytest.raises(KeyError):
        reg.embedding()
    assert reg.embedding_or_none() is None


def test_by_type_by_modality_and_descriptors() -> None:
    reg = DriverRegistry()
    chat, db = _FakeChat(), _FakeDb()
    reg.register(chat)
    reg.register(db)
    assert reg.by_type("database") == [db]
    assert reg.by_modality("chat") == [chat]
    assert reg.types() == ["database", "model"]
    assert [d.name for d in reg.descriptors()] == ["db-main", "fake-chat"]


@pytest.mark.asyncio
async def test_aclose_all_closes_everything() -> None:
    reg = DriverRegistry()
    a, b = _FakeChat("chat-a"), _FakeChat("chat-b")
    reg.register(a)
    reg.register(b)
    await reg.aclose_all()
    assert a.closed and b.closed
