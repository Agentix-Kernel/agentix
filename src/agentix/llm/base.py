"""MIGRATION SHIM — removed in 0.5.0 final; import from ``agentix.drivers``.

The canonical chat wire types live in ``agentix.drivers.chat``
(``ChatRequest``/``ChatResponse``/``ToolSpec``/``tool_to_spec``); the old
``Llm*`` names below are module-level aliases. The ``LlmError`` family and
the ``Provider`` protocol remain here for the migration window only —
``Provider`` is the pre-driver chat surface (no ``descriptor``); new code
targets ``agentix.drivers.chat.ChatDriver``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agentix.drivers.base import DriverError
from agentix.drivers.chat import (
    ChatRequest,
    ChatResponse,
    ToolSpec,
    tool_to_spec,
)

__all__ = [
    "LlmError",
    "LlmInvalidRequest",
    "LlmRateLimit",
    "LlmRequest",
    "LlmResponse",
    "LlmUnavailable",
    "Provider",
    "ToolSpec",
    "tool_to_spec",
]

# Canonical types, old names. Identity aliases — ``LlmRequest is ChatRequest``.
LlmRequest = ChatRequest
LlmResponse = ChatResponse


class LlmError(DriverError):
    """Base class for provider errors surfaced to the router.

    Re-based on the driver taxonomy (``agentix.drivers.base.DriverError``) —
    the chat family's errors ARE driver errors. ``provider`` is kept as a
    read-only alias of ``driver`` for the migration window (removed in
    0.5.0 final).
    """

    def __init__(self, message: str, *, provider: str, retryable: bool = False) -> None:
        super().__init__(message, driver=provider, retryable=retryable)

    @property
    def provider(self) -> str:
        return self.driver


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
    """Pre-driver chat protocol (no ``descriptor``). Migration alias surface."""

    name: str
    default_model: str

    async def complete(self, request: ChatRequest) -> ChatResponse:
        """Issue a single non-streaming chat completion."""
        ...

    async def aclose(self) -> None:
        """Release underlying HTTP resources."""
        ...
