"""Kernel configuration — the resolved settings the engine + providers need.

``KernelConfig`` is the app-agnostic config the kernel runtime factories
(:mod:`agentix.runtime`) consume: storage locations, the LLM provider configs, the
per-session budget, and the pricing table. Apps subclass it to add their own resolved
settings (e.g. the migration app's ``ResolvedConfig`` adds Odoo credentials + customers).

The kernel takes a *resolved* config object — it does not load YAML/env. Apps own loading
and pass a populated ``KernelConfig`` (or subclass) in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agentix.core.middleware.cost_tracking import ModelPricing
from agentix.storage import MinioConfig


@dataclass(frozen=True)
class AnthropicConfig:
    """Per-provider config for AnthropicProvider.

    ``keychain_service`` names the macOS Keychain entry Claude Code writes on
    login (default ``Claude Code-credentials``); when set, re-read per-request
    so rotations land on the next call. ``oauth_credentials_path`` is the
    file-path fallback for non-macOS setups.
    """

    oauth_credentials_path: Path | None = None
    keychain_service: str | None = None
    api_key: str | None = None
    model: str | None = None


@dataclass(frozen=True)
class HubleConfig:
    """HUBLE gateway config.

    When ``enabled=True``, the runtime builds a :class:`agentix.llm.huble.HubleProvider`
    so every LLM call routes through HUBLE.
    """

    enabled: bool = False
    base_url: str | None = None  # falls back to LLMHUB_URL env / http://localhost:4000
    api_key: str | None = None  # falls back to LLMHUB_API_KEY env
    upstream_provider: str = "melious"
    model: str = "deepseek-v3.2"
    # HUBLE-served embedding model. When set, runners construct a
    # HubleEmbeddingProvider for ToolContext.embeddings; None → Jaccard fallback.
    embedding_model: str | None = None
    embeddings_path: str = "/api/v2/embeddings"


@dataclass(frozen=True)
class MeliousConfig:
    """Direct Melious chat provider (OpenAI-compatible wire format).

    Primary LLM route when enabled (no gateway hop). deepseek models return
    reasoning in a separate ``reasoning_content`` field, not ``content``.
    """

    enabled: bool = False
    base_url: str | None = None  # falls back to MELIOUS_BASE_URL env
    api_key: str | None = None  # falls back to MELIOUS_API_KEY env
    model: str = "deepseek-v4-flash"


@dataclass(frozen=True)
class LlmPricingConfig:
    """Per-model USD-per-million-token prices from the ``llm_pricing:`` block.

    Keys match the provider-returned model id. Missing models fall through to
    ``FALLBACK_PRICING['__unknown__']`` (over-counts). Date-stamped ids
    (``claude-sonnet-4-6-20260101`` → ``claude-sonnet-4-6``) are prefix-matched
    by ``cost_tracking._lookup_pricing``.
    """

    models: dict[str, ModelPricing] = field(default_factory=dict)

    def as_table(self) -> dict[str, ModelPricing]:
        """Return the pricing table merged with the ``__unknown__`` fallback."""
        from agentix.core.middleware.cost_tracking import FALLBACK_PRICING

        return {**FALLBACK_PRICING, **self.models}


@dataclass(frozen=True)
class KernelConfig:
    """Resolved kernel settings consumed by :mod:`agentix.runtime`.

    Apps subclass this to attach their own resolved settings. All app-extension fields
    must carry defaults (frozen-dataclass inheritance appends them after these).
    """

    config_path: Path
    minio: MinioConfig
    sqlite_path: Path
    memory_path: Path
    anthropic: AnthropicConfig = AnthropicConfig()
    huble: HubleConfig = HubleConfig()
    melious: MeliousConfig = MeliousConfig()
    budget_usd: float = 200.0
    # Per-model USD pricing for cost telemetry + budget enforcement. Empty →
    # ``__unknown__`` fallback in CostTrackingMiddleware.
    llm_pricing: LlmPricingConfig = field(default_factory=LlmPricingConfig)
