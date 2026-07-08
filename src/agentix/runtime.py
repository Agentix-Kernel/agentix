"""Engine-side runtime factories — LLM provider + embedding provider.

Build the provider chain and embedding provider from a ``ResolvedConfig``,
independent of any interface. Extracted from ``cli/main.py`` so the broker
worker (and any engine caller) can construct providers without importing the
CLI package (Locked #3). The CLI re-imports these.
"""

from __future__ import annotations

from typing import Any

from agentix.config import KernelConfig, enabled_providers
from agentix.storage import SqliteStore


def build_llm_provider(  # type: ignore[no-untyped-def]
    cfg: KernelConfig,
    sqlite: SqliteStore | None = None,
    model_override: str | None = None,
    always_router: bool = False,
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

    **always_router**: wrap even a single provider in a
    ``ProviderRouter``, for callers that depend on the router surface
    (e.g. ``set_failover_callback``) and would otherwise need
    isinstance special-casing.
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

    # Per-provider object construction. The *activation* decision (which
    # providers are active + failover order) is owned by
    # ``agentix.config.enabled_providers`` — the single source of truth the
    # app config loader also consumes, so the two can't drift.
    def _build(name: str, pc: Any) -> Any:
        if name == "melious":
            # Direct Melious — OpenAI-compatible wire, no gateway hop.
            return OpenAIProvider(
                base_url=pc.base_url or os.environ.get("MELIOUS_BASE_URL"),
                api_key=pc.api_key or os.environ.get("MELIOUS_API_KEY"),
                model=model_override or pc.model,
            )
        if name == "huble":
            return HubleProvider(
                base_url=pc.base_url,
                api_key=pc.api_key,
                upstream_provider=pc.upstream_provider,
                model=model_override or pc.model,
            )
        return AnthropicProvider(
            api_key=pc.api_key,
            oauth_credentials_path=pc.oauth_credentials_path,
            keychain_service=pc.keychain_service,
            model=pc.model,
        )

    providers: list[Any] = [_wrap(_build(name, pc)) for name, pc in enabled_providers(cfg)]
    if not providers:
        # Last-resort: Anthropic with defaults when no provider configured.
        providers.append(_wrap(AnthropicProvider(model=cfg.anthropic.model)))
    if len(providers) == 1 and not always_router:
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
