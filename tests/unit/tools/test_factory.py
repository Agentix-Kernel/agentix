"""@tool declarative factory (#77) — declaration validation, hint inference,
protocol conformance, and specs() parity with the class path."""

from __future__ import annotations

from typing import Any, cast

import pytest
from pydantic import BaseModel

from agentix.tools.base import Tool, ToolContext
from agentix.tools.factory import FunctionTool, tool
from agentix.tools.registry import ToolRegistry


class _In(BaseModel):
    x: int


class _Out(BaseModel):
    y: int


def _ctx() -> ToolContext:
    # The factory shell never touches the context; a hollow one suffices.
    return cast(ToolContext, object.__new__(ToolContext))


# ───────────────────────── declaration + inference ─────────────────────────


def test_infers_models_name_and_description_from_function() -> None:
    @tool()
    async def double(params: _In, ctx: ToolContext) -> _Out:
        """Double the input."""
        return _Out(y=params.x * 2)

    assert isinstance(double, FunctionTool)
    assert double.name == "double"
    assert double.description == "Double the input."
    assert double.input_schema is _In
    assert double.output_schema is _Out
    assert double.mutates_target is False
    assert double.verifier is None
    assert double.required_provider is None


def test_explicit_kwargs_override_inference() -> None:
    @tool(name="alias", description="Explicit.", input_model=_In, output_model=_Out, required_provider="llm")
    async def whatever(params: Any, ctx: ToolContext) -> Any:
        """Ignored — description= wins."""
        return _Out(y=0)

    assert whatever.name == "alias"
    assert whatever.description == "Explicit."
    assert whatever.input_schema is _In
    assert whatever.required_provider == "llm"


def test_rejects_sync_function_missing_hints_and_bad_arity() -> None:
    with pytest.raises(TypeError, match="must be async"):

        @tool()
        def sync_fn(params: _In, ctx: ToolContext) -> _Out:  # type: ignore[arg-type]
            """Nope."""
            return _Out(y=0)

    with pytest.raises(TypeError, match="input model"):

        @tool()
        async def unhinted(params, ctx):  # type: ignore[no-untyped-def]
            """No hints, no input_model=."""
            return _Out(y=0)

    with pytest.raises(TypeError, match="expected exactly"):

        @tool(input_model=_In, output_model=_Out)
        async def one_arg(params: _In) -> _Out:  # type: ignore[arg-type]
            """Wrong arity."""
            return _Out(y=0)


def test_requires_a_description_and_verifier_for_mutating() -> None:
    with pytest.raises(ValueError, match="description is required"):

        @tool()
        async def undocumented(params: _In, ctx: ToolContext) -> _Out:
            return _Out(y=0)

    with pytest.raises(ValueError, match="requires a verifier"):

        @tool(mutates_target=True)
        async def unverified(params: _In, ctx: ToolContext) -> _Out:
            """Mutates without a verifier — declaration-time error."""
            return _Out(y=0)


# ───────────────────────── protocol + dispatch surface ─────────────────────────


@pytest.mark.asyncio
async def test_call_coerces_input_and_satisfies_protocol() -> None:
    @tool()
    async def double(params: _In, ctx: ToolContext) -> _Out:
        """Double the input."""
        return _Out(y=params.x * 2)

    assert isinstance(double, Tool)  # runtime-checkable protocol

    class _Sibling(BaseModel):  # dispatcher may hand a sibling-shaped model
        x: int

    result = await double.call(_Sibling(x=21), _ctx())
    assert isinstance(result, _Out) and result.y == 42
    # the raw function stays reachable for direct composition
    assert (await double.fn(_In(x=1), _ctx())).y == 2


def test_registry_specs_parity_with_class_tool() -> None:
    """The advertised catalog entry is identical however the tool is built —
    the acceptance criterion of the app-side migration (CRIE 004 T2)."""

    class ClassTool:
        name = "parity"
        description = "Parity check."
        input_schema = _In
        output_schema = _Out
        mutates_target = False
        verifier: str | None = None

        async def call(self, input: BaseModel, ctx: ToolContext) -> BaseModel:
            return _Out(y=0)

    @tool(name="parity", description="Parity check.")
    async def parity(params: _In, ctx: ToolContext) -> _Out:
        return _Out(y=0)

    specs = []
    for t in (ClassTool(), parity):
        registry = ToolRegistry()
        registry.register(cast(Tool, t))
        specs.append(registry.specs()[0].model_dump())
    assert specs[0] == specs[1]


def test_provider_gate_respected_by_registry() -> None:
    @tool(required_provider="llm")
    async def needs_llm(params: _In, ctx: ToolContext) -> _Out:
        """LLM-gated."""
        return _Out(y=0)

    registry = ToolRegistry()
    assert registry.register_provider_gated(cast(Tool, needs_llm), available=set()) is False
    assert registry.register_provider_gated(cast(Tool, needs_llm), available={"anthropic"}) is True
    assert "needs_llm" in registry


def test_closure_builder_pattern_binds_dependencies() -> None:
    """Dep-carrying tools close over their deps via a builder function."""

    def build(dep: int) -> FunctionTool:
        @tool(name="closured", description="Adds a closed-over dep.")
        async def _closured(params: _In, ctx: ToolContext) -> _Out:
            return _Out(y=params.x + dep)

        return _closured

    built = build(100)
    assert built.name == "closured"
