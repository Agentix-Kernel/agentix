"""register_provider_gated — declarative provider gating for tool registration."""

from __future__ import annotations

from pydantic import BaseModel

from agentix.tools.registry import ToolRegistry


class _IO(BaseModel):
    pass


class _FakeTool:
    """Minimal structural Tool. ``required_provider`` optionally set per-instance."""

    def __init__(self, name: str, required_provider: str | None = None) -> None:
        self.name = name
        self.description = "fake"
        self.input_schema = _IO
        self.output_schema = _IO
        self.mutates_target = False
        self.verifier = None
        if required_provider is not None:
            self.required_provider = required_provider

    async def call(self, input: BaseModel, ctx: object) -> BaseModel:
        return _IO()


def test_no_requirement_always_registers() -> None:
    reg = ToolRegistry()
    assert reg.register_provider_gated(_FakeTool("plain"), available=set()) is True
    assert "plain" in reg


def test_llm_sentinel_registers_when_any_provider_available() -> None:
    reg = ToolRegistry()
    tool = _FakeTool("diagnose", required_provider="llm")
    assert reg.register_provider_gated(tool, available={"anthropic"}) is True
    assert "diagnose" in reg


def test_llm_sentinel_skips_when_no_provider() -> None:
    reg = ToolRegistry()
    tool = _FakeTool("diagnose", required_provider="llm")
    assert reg.register_provider_gated(tool, available=set()) is False
    assert "diagnose" not in reg


def test_named_provider_must_match() -> None:
    reg = ToolRegistry()
    assert reg.register_provider_gated(_FakeTool("t1", required_provider="anthropic"), available={"huble"}) is False
    assert reg.register_provider_gated(_FakeTool("t2", required_provider="anthropic"), available={"anthropic"}) is True
    assert "t1" not in reg
    assert "t2" in reg
