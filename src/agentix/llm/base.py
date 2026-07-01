"""LLM provider protocol + request/response types.

Direct SDK usage per arch.md §11 — no `litellm` wrapper. Each
provider adapter has to translate the kernel's canonical ``LlmRequest`` into
its vendor-specific shape and back. The router lives above the protocol
(``agentix.llm.router``) and sequences providers for fallback.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from agentix.core.types import Message, TokenUsage, ToolCall


class ToolSpec(BaseModel):
    """Canonical tool description the LLM needs to know how to call a tool.

    Providers translate this shape to their own wire format:

      * Anthropic: ``{name, description, input_schema}`` (JSON Schema).
      * OpenAI / Groq: ``{"type": "function", "function": {name,
        description, parameters}}`` (parameters = our ``input_schema``).

    The translation lives in each provider adapter (). Callers build
    ``ToolSpec`` instances via:func:`tool_to_spec` so the input schema
    comes straight off the tool's declared pydantic input model.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    input_schema: dict[str, Any] = Field(
        description="JSON Schema for the tool's input. Usually produced by ``Tool.input_schema.model_json_schema()``.",
    )


def tool_to_spec(tool: Any) -> ToolSpec:
    """Project a:class:`agentix.tools.base.Tool` into a canonical:class:`ToolSpec`.

    ``tool.input_schema`` is a pydantic model class; we ask it for its
    JSON Schema and pass that along. Kept as a module-level function (not
    a Tool method) so:mod:`agentix.llm.base` stays free of import cycles
    with:mod:`ludo.tools`.
    """
    schema_cls = getattr(tool, "input_schema", None)
    if schema_cls is None or not hasattr(schema_cls, "model_json_schema"):
        raise TypeError(f"tool_to_spec: tool {tool!r} has no pydantic input_schema to project")
    return ToolSpec(
        name=str(tool.name),
        description=str(getattr(tool, "description", "")),
        input_schema=schema_cls.model_json_schema(),
    )


class LlmRequest(BaseModel):
    """Canonical request shape passed to any provider."""

    model_config = ConfigDict(extra="forbid")

    messages: list[Message]
    model: str | None = None  # provider defaults when unset
    # Output budget default is GENEROUS by design. A stingy default
    # silently truncates structured outputs mid-JSON — the caller pays
    # for every token and gets nothing parseable (reasoning-style models
    # burn output budget on thinking before emitting content). Spend
    # control belongs to the TokenBudget middleware ($ per session), not
    # to silent truncation. Call sites with known-tiny outputs may lower
    # this for latency; that is the exception.
    max_tokens: int = 16_384
    temperature: float = 1.0

    # Per-vendor-feature passthroughs — providers pick what they support.
    thinking_enabled: bool = False
    thinking_budget_tokens: int | None = None
    reasoning_effort: Literal["low", "medium", "high"] | None = None
    cache_control: bool = False
    stop_sequences: list[str] | None = None

    # Tool-use (). Providers that don't support tools silently ignore
    # these; providers that do translate to their own wire format.
    tools: list[ToolSpec] | None = None
    tool_choice: Literal["auto", "any", "none"] | None = None

    extra_params: dict[str, Any] = Field(default_factory=dict)


class LlmResponse(BaseModel):
    """Canonical response shape emitted by any provider."""

    model_config = ConfigDict(extra="forbid")

    content: str
    usage: TokenUsage = Field(default_factory=TokenUsage)
    model: str
    finish_reason: str | None = None
    # Tool-use (). Non-empty when the model emitted tool_use blocks
    # (Anthropic) or tool_calls (OpenAI/Groq). The AgentDispatcher ()
    # loops while this is non-empty.
    tool_calls: list[ToolCall] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class LlmError(Exception):
    """Base class for provider errors surfaced to the router."""

    def __init__(self, message: str, *, provider: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable


class LlmRateLimit(LlmError):
    """Provider signalled a rate limit. Always retryable (router fallback)."""

    def __init__(self, message: str, *, provider: str) -> None:
        super().__init__(message, provider=provider, retryable=True)


class LlmUnavailable(LlmError):
    """Provider is temporarily unreachable (5xx, timeout). Retryable."""

    def __init__(self, message: str, *, provider: str) -> None:
        super().__init__(message, provider=provider, retryable=True)


class LlmInvalidRequest(LlmError):
    """The request itself is malformed — do not retry the same payload."""

    def __init__(self, message: str, *, provider: str) -> None:
        super().__init__(message, provider=provider, retryable=False)


@runtime_checkable
class Provider(Protocol):
    """Protocol every LLM adapter implements."""

    name: str
    default_model: str

    async def complete(self, request: LlmRequest) -> LlmResponse:
        """Issue a single non-streaming chat completion."""
        ...

    async def aclose(self) -> None:
        """Release underlying HTTP resources."""
        ...
