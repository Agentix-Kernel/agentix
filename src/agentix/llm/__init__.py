"""LLM provider layer — Claude OAuth primary, OpenAI + Groq fallbacks."""

from agentix.llm.anthropic import AnthropicProvider
from agentix.llm.base import (
    LlmError,
    LlmInvalidRequest,
    LlmRateLimit,
    LlmRequest,
    LlmResponse,
    LlmUnavailable,
    Provider,
    ToolSpec,
    tool_to_spec,
)
from agentix.llm.groq import GroqProvider
from agentix.llm.openai import OpenAIProvider
from agentix.llm.router import NoProvidersAvailable, ProviderRouter

__all__ = [
    "AnthropicProvider",
    "GroqProvider",
    "LlmError",
    "LlmInvalidRequest",
    "LlmRateLimit",
    "LlmRequest",
    "LlmResponse",
    "LlmUnavailable",
    "NoProvidersAvailable",
    "OpenAIProvider",
    "Provider",
    "ProviderRouter",
    "ToolSpec",
    "tool_to_spec",
]
