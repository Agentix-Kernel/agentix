"""Provider router — primary + fallback chain.

The router holds an ordered list of providers and dispatches a request
to each in turn on retryable failure. First success wins. If every
provider in the chain returns a retryable error, the final error is
re-raised so callers can decide whether to abort or retry later.

Cost-aware routing (prefer cheapest provider that satisfies the request)
is a v0.2 feature — v0.1 ships with a simple ordered fallback.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import structlog

from agentix.llm.base import (
    LlmError,
    LlmInvalidRequest,
    LlmRequest,
    LlmResponse,
    Provider,
)

# Failover callback signature: (failed_provider_name, next_provider_name, error)
# Async so callers can publish to the event bus without blocking the dispatch.
FailoverCallback = Callable[[str, str, LlmError], Awaitable[None]]

log = structlog.get_logger(__name__)


class NoProvidersAvailable(LlmError):
    """Every configured provider failed for the request."""

    def __init__(self, attempts: list[tuple[str, str]]) -> None:
        detail = "; ".join(f"{name}: {err}" for name, err in attempts)
        super().__init__(f"all providers failed ({detail})", provider="router", retryable=False)
        self.attempts = attempts


class ProviderRouter:
    """Routes an ``LlmRequest`` through an ordered fallback chain.

    Protocol-compatible with:class:`agentix.llm.base.Provider` so callers
    can use a router anywhere a single Provider is expected. ``name`` is
    fixed at ``"router"``; ``default_model`` proxies to the FIRST
    provider's default (the typical primary). Cost tracking sees per-call
    response model anyway, so the fallback's actual model still gets
    billed correctly when it answers.
    """

    name: str = "router"

    def __init__(
        self,
        providers: list[Provider],
        *,
        on_failover: FailoverCallback | None = None,
    ) -> None:
        if not providers:
            raise ValueError("ProviderRouter requires at least one provider")
        self._providers = providers
        self._on_failover = on_failover

    @property
    def default_model(self) -> str:
        return self._providers[0].default_model

    @property
    def providers(self) -> list[Provider]:
        return list(self._providers)

    def set_failover_callback(self, cb: FailoverCallback | None) -> None:
        """Attach (or clear) the failover hook after construction.

        Pattern: the CLI builds the router with no callback; the agent
        runner closes over the session id (created later) and attaches
        a session-aware callback via this method. Avoids the chicken-
        and-egg of needing the session at provider-construction time.
        """
        self._on_failover = cb

    async def complete(self, request: LlmRequest) -> LlmResponse:
        attempts: list[tuple[str, str]] = []
        for i, provider in enumerate(self._providers):
            try:
                response = await provider.complete(request)
                log.debug("router.provider_ok", provider=provider.name, model=response.model)
                return response
            except LlmInvalidRequest:
                # Non-retryable — bail out immediately, the next provider
                # would fail for the same reason (malformed payload).
                raise
            except LlmError as exc:
                log.warning(
                    "router.provider_failed",
                    provider=provider.name,
                    retryable=exc.retryable,
                    error=str(exc),
                )
                attempts.append((provider.name, str(exc)))
                if not exc.retryable:
                    raise
                # Follow-up B: emit a failover event when there's a
                # next provider to try. Skip on the LAST attempt — that's
                # not a failover, that's exhaustion (raises below).
                if self._on_failover is not None and i + 1 < len(self._providers):
                    next_provider = self._providers[i + 1]
                    try:
                        await self._on_failover(provider.name, next_provider.name, exc)
                    except Exception as cb_exc:  # pragma: no cover — best-effort
                        log.warning(
                            "router.failover_callback_failed",
                            error=f"{type(cb_exc).__name__}: {cb_exc}"[:200],
                        )
        raise NoProvidersAvailable(attempts)

    async def aclose(self) -> None:
        for provider in self._providers:
            try:
                await provider.aclose()
            except Exception as exc:  # pragma: no cover — best-effort close
                log.warning("router.close_failed", provider=provider.name, error=str(exc))
