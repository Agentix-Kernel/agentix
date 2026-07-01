"""Engine-side runtime factories — LLM provider + embedding provider.

Build the provider chain and embedding provider from a ``ResolvedConfig``,
independent of any interface. Extracted from ``cli/main.py`` so the broker
worker (and any engine caller) can construct providers without importing the
CLI package (Locked #3). The CLI re-imports these.
"""

from __future__ import annotations

from typing import Any

from agentix.config import KernelConfig
from agentix.storage import SqliteStore


def build_llm_provider(  # type: ignore[no-untyped-def]
    cfg: KernelConfig,
    sqlite: SqliteStore | None = None,
    model_override: str | None = None,
):
    """Build the LLM provider chain with auto-failover.

    Multiple configured providers return a ``ProviderRouter`` that
    falls over on LlmUnavailable / LlmRateLimit; a single provider is
    returned directly.

    **model_override**: replaces the HUBLE/Melious provider ``model``
    for this invocation. Anthropic fallback model stays as configured.

    **sqlite**: when provided, each underlying provider is wrapped in
    :class:`CostRecordingProvider`, recording cost to SQLite per
    successful LLM call. Optional for non-migration call sites with no
    session row.
    """
    import os

    from agentix.llm import AnthropicProvider
    from agentix.llm.cost_recorder import CostRecordingProvider
    from agentix.llm.huble import HubleProvider
    from agentix.llm.openai import OpenAIProvider
    from agentix.llm.router import ProviderRouter

    pricing_table = cfg.llm_pricing.as_table()

    def _wrap(p: Any) -> Any:
        return CostRecordingProvider(p, sqlite=sqlite, pricing_table=pricing_table) if sqlite is not None else p

    providers: list[Any] = []
    if cfg.melious.enabled:
        # Direct Melious — OpenAI-compatible wire, no gateway hop.
        providers.append(
            _wrap(
                OpenAIProvider(
                    base_url=cfg.melious.base_url or os.environ.get("MELIOUS_BASE_URL"),
                    api_key=cfg.melious.api_key or os.environ.get("MELIOUS_API_KEY"),
                    model=model_override or cfg.melious.model,
                )
            )
        )
    if cfg.huble.enabled:
        huble_model = model_override or cfg.huble.model
        providers.append(
            _wrap(
                HubleProvider(
                    base_url=cfg.huble.base_url,
                    api_key=cfg.huble.api_key,
                    upstream_provider=cfg.huble.upstream_provider,
                    model=huble_model,
                )
            )
        )
    ac = cfg.anthropic
    if ac.api_key or ac.oauth_credentials_path or ac.keychain_service:
        providers.append(
            _wrap(
                AnthropicProvider(
                    api_key=ac.api_key,
                    oauth_credentials_path=ac.oauth_credentials_path,
                    keychain_service=ac.keychain_service,
                    model=ac.model,
                )
            )
        )
    if not providers:
        # Last-resort: Anthropic with defaults when no provider configured.
        providers.append(_wrap(AnthropicProvider(model=ac.model)))
    if len(providers) == 1:
        return providers[0]
    return ProviderRouter(providers)


def build_embedding_provider(cfg: KernelConfig, sqlite: SqliteStore) -> object | None:
    """Construct a CachedEmbeddingProvider from configured HUBLE embeddings
    (or OPENAI_API_KEY fallback).

    Returns None when no embedding backend is configured; callers thread
    None into ToolContext.embeddings and downstream code falls back to
    the Jaccard baseline.
    """
    import os

    from agentix.embeddings import (
        CachedEmbeddingProvider,
        EmbeddingCache,
        EmbeddingError,
        HubleEmbeddingProvider,
        OpenAIEmbeddingProvider,
    )

    if cfg.huble.enabled and cfg.huble.embedding_model and cfg.huble.api_key and cfg.huble.base_url:
        try:
            huble_upstream = HubleEmbeddingProvider(
                base_url=cfg.huble.base_url,
                api_key=cfg.huble.api_key,
                model=cfg.huble.embedding_model,
                embeddings_path=cfg.huble.embeddings_path,
            )
            return CachedEmbeddingProvider(upstream=huble_upstream, cache=EmbeddingCache(sqlite=sqlite))
        except EmbeddingError:
            return None
    if os.environ.get("OPENAI_API_KEY"):
        try:
            openai_upstream = OpenAIEmbeddingProvider()
            return CachedEmbeddingProvider(upstream=openai_upstream, cache=EmbeddingCache(sqlite=sqlite))
        except EmbeddingError:
            return None
    return None
