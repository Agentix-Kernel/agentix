"""Declarative tool construction — ``@tool`` over an async function (#77).

The second, ADDITIVE construction path beside the class protocol: a tool
whose whole identity is one async function needs no class shell. The
decorator produces a :class:`FunctionTool` INSTANCE (not a class), ready to
hand to ``ToolRegistry.register`` — name, schemas and flags are declared
once, at the definition site.

.. code:: python

    @tool(mutates_target=False)
    async def pin_record(params: PinRecordInput, ctx: ToolContext) -> PinRecordOutput:
        \"\"\"Advertised description (or pass ``description=`` explicitly).\"\"\"
        ...

Input/output models are inferred from the type hints (first parameter /
return) unless ``input_model=``/``output_model=`` override them; the tool
name defaults to the function name; input coercion (``ensure_input``) is
applied by the shell, so the function body always receives its own model.

Tools that carry dependencies (a provider handle, sibling-tool facades)
close over them — define the decorated function inside a builder::

    def build_discover(provider: ChatDriver | None) -> FunctionTool:
        @tool(name="discover_renames", description=..., mutates_target=False)
        async def _discover(params: DiscoverInput, ctx: ToolContext) -> DiscoverOutput:
            ...uses provider...
        return _discover

The class path stays first-class (kernel builtins keep it); the registry,
dispatcher, safety gate and ``specs()`` treat both identically.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any, get_type_hints

from pydantic import BaseModel

from agentix.tools.base import ToolContext, ensure_input

__all__ = ["FunctionTool", "tool"]

# The decorated function's params may be (and should be) narrower than
# BaseModel — contravariance forbids expressing that in a plain Callable,
# so the alias is loose and the decorator validates at declaration time.
ToolFn = Callable[[Any, ToolContext], Awaitable[BaseModel]]


class FunctionTool:
    """A tool built from one async function; satisfies the ``Tool`` protocol.

    The dispatcher-facing surface (name/description/schemas/flags/``call``)
    is exactly the class tool's; the wrapped function stays reachable as
    ``.fn`` for direct composition (facades forwarding to siblings, tests).
    """

    def __init__(
        self,
        fn: ToolFn,
        *,
        name: str,
        description: str,
        input_schema: type[BaseModel],
        output_schema: type[BaseModel],
        mutates_target: bool = False,
        verifier: str | None = None,
        required_provider: str | None = None,
        default_timeout_seconds: float | None = None,
    ) -> None:
        # Same invariant the registry enforces, moved to declaration time —
        # a mutating tool without a verifier fails at import, not at startup.
        if mutates_target and not verifier:
            raise ValueError(f"tool {name!r}: mutates_target=True requires a verifier")
        self.fn = fn
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.output_schema = output_schema
        self.mutates_target = mutates_target
        self.verifier = verifier
        self.required_provider = required_provider
        # Per-tool dispatch timeout override. The dispatcher reads it via
        # ``getattr(tool, "default_timeout_seconds", None) or <chain default>``,
        # so None is equivalent to absent — long-running tools declare their
        # budget here instead of poking an attribute onto the instance.
        self.default_timeout_seconds = default_timeout_seconds
        self.__doc__ = fn.__doc__

    def __repr__(self) -> str:
        return f"FunctionTool({self.name!r})"

    async def call(self, input: BaseModel, ctx: ToolContext) -> BaseModel:
        return await self.fn(ensure_input(input, self.input_schema), ctx)


def tool(
    *,
    name: str | None = None,
    description: str | None = None,
    mutates_target: bool = False,
    verifier: str | None = None,
    required_provider: str | None = None,
    input_model: type[BaseModel] | None = None,
    output_model: type[BaseModel] | None = None,
    default_timeout_seconds: float | None = None,
) -> Callable[[ToolFn], FunctionTool]:
    """Build a :class:`FunctionTool` from ``async def fn(params, ctx) -> Output``.

    ``name`` defaults to the function name; ``description`` to the cleaned
    docstring (one of the two MUST yield text — the description is what the
    LLM sees); input/output models come from the type hints unless passed
    explicitly. Declaration errors raise immediately (import time), never
    at dispatch.
    """

    def decorate(fn: ToolFn) -> FunctionTool:
        tool_name = name or fn.__name__
        if not inspect.iscoroutinefunction(fn):
            raise TypeError(f"tool {tool_name!r}: the decorated function must be async")
        params = list(inspect.signature(fn).parameters)
        if len(params) != 2:
            raise TypeError(f"tool {tool_name!r}: expected exactly (params, ctx), got {params}")

        hints = get_type_hints(fn)
        in_model = input_model or hints.get(params[0])
        out_model = output_model or hints.get("return")
        for label, model in (("input", in_model), ("output", out_model)):
            if not (isinstance(model, type) and issubclass(model, BaseModel)):
                raise TypeError(
                    f"tool {tool_name!r}: {label} model must be a BaseModel subclass — "
                    f"annotate the function or pass {label}_model= (got {model!r})"
                )
        assert isinstance(in_model, type) and isinstance(out_model, type)  # for the type-checker

        desc = description if description is not None else inspect.cleandoc(fn.__doc__ or "")
        if not desc:
            raise ValueError(f"tool {tool_name!r}: a description is required (docstring or description=)")

        return FunctionTool(
            fn,
            name=tool_name,
            description=desc,
            input_schema=in_model,
            output_schema=out_model,
            mutates_target=mutates_target,
            verifier=verifier,
            required_provider=required_provider,
            default_timeout_seconds=default_timeout_seconds,
        )

    return decorate
