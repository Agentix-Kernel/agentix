"""Grok provider — xAI's OpenAI-compatible adapter.

xAI exposes an OpenAI-compatible endpoint at ``https://api.x.ai/v1``.
This adapter points ``OpenAIChatDriver`` at that endpoint.

Auth: ``XAI_API_KEY`` env var or explicit ``api_key``.
ToS: https://x.ai/legal/terms-of-service — consumer must accept independently.
"""

from __future__ import annotations

import os

from agentix.drivers.adapters.vendor.openai import OpenAIChatDriver
from agentix.drivers.base import DriverDescriptor, DriverInvalidRequest

__all__ = ["GrokChatDriver"]

_XAI_BASE_URL = "https://api.x.ai/v1"
_DEFAULT_MODEL = "grok-3"


class GrokChatDriver(OpenAIChatDriver):
    """Grok (xAI) chat via the OpenAI-compatible endpoint."""

    name = "grok"

    @property
    def descriptor(self) -> DriverDescriptor:
        return DriverDescriptor(
            name=self.name,
            type="model",
            modality="chat",
            source="api",
            capabilities=frozenset({"tools"}),
            default_model=self.default_model,
            pricing_ref=self.default_model,
        )

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 300.0,
        base_url: str | None = None,
    ) -> None:
        key = api_key or os.environ.get("XAI_API_KEY")
        if not key:
            raise DriverInvalidRequest(
                "no xAI API key (set XAI_API_KEY or pass api_key)",
                driver=self.name,
            )
        super().__init__(
            api_key=key,
            model=model or _DEFAULT_MODEL,
            timeout_seconds=timeout_seconds,
            base_url=base_url or _XAI_BASE_URL,
        )
