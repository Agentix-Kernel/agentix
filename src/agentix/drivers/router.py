"""Chat failover chain — primary + fallback drivers.

The chain holds an ordered list of chat drivers and dispatches a request
to each in turn on retryable failure. First success wins. If every
driver in the chain fails retryably, the exhaustion error is raised so
callers can decide whether to abort or retry later.

Routing *policy* (cost-aware / capability-aware candidate ordering) is
DIRECTION — see ``docs/routing.md`` §4/§6; the chain owns only the
failover mechanics.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import structlog

from agentix.drivers.base import DriverDescriptor, DriverError, DriverInvalidRequest
from agentix.drivers.chat import ChatDriver, ChatRequest, ChatResponse

# Failover callback signature: (failed_driver_name, next_driver_name, error)
# Async so callers can publish to the event bus without blocking the dispatch.
FailoverCallback = Callable[[str, str, DriverError], Awaitable[None]]

log = structlog.get_logger(__name__)


class NoDriversAvailable(DriverError):
    """Every configured driver failed for the request."""

    def __init__(self, attempts: list[tuple[str, str]]) -> None:
        detail = "; ".join(f"{name}: {err}" for name, err in attempts)
        super().__init__(f"all providers failed ({detail})", driver="router", retryable=False)
        self.attempts = attempts


class ChatFailoverChain:
    """Routes a ``ChatRequest`` through an ordered fallback chain.

    Protocol-compatible with :class:`agentix.drivers.chat.ChatDriver` so
    callers can use a chain anywhere a single driver is expected. ``name``
    is fixed at ``"router"``; ``default_model`` proxies to the FIRST
    driver's default (the typical primary). Cost tracking sees per-call
    response model anyway, so the fallback's actual model still gets
    billed correctly when it answers.
    """

    name: str = "router"

    def __init__(
        self,
        providers: list[ChatDriver],
        *,
        on_failover: FailoverCallback | None = None,
    ) -> None:
        if not providers:
            raise ValueError("ChatFailoverChain requires at least one provider")
        self._providers = providers
        self._on_failover = on_failover

    @property
    def descriptor(self) -> DriverDescriptor:
        # Synthesized (not forwarded): inner drivers may still be
        # pre-driver Provider objects during the migration window.
        return DriverDescriptor(
            name=self.name,
            kind="model",
            modality="chat",
            source="api",
            default_model=self.default_model,
        )

    @property
    def default_model(self) -> str:
        return self._providers[0].default_model

    @property
    def providers(self) -> list[ChatDriver]:
        return list(self._providers)

    def set_failover_callback(self, cb: FailoverCallback | None) -> None:
        """Attach (or clear) the failover hook after construction.

        Pattern: the app builds the chain with no callback; the agent
        runner closes over the session id (created later) and attaches
        a session-aware callback via this method. Avoids the chicken-
        and-egg of needing the session at driver-construction time.
        """
        self._on_failover = cb

    async def complete(self, request: ChatRequest) -> ChatResponse:
        attempts: list[tuple[str, str]] = []
        for i, provider in enumerate(self._providers):
            try:
                response = await provider.complete(request)
                log.debug("router.provider_ok", provider=provider.name, model=response.model)
                return response
            except DriverInvalidRequest:
                # Non-retryable — bail out immediately, the next driver
                # would fail for the same reason (malformed payload).
                raise
            except DriverError as exc:
                log.warning(
                    "router.provider_failed",
                    provider=provider.name,
                    retryable=exc.retryable,
                    error=str(exc),
                )
                attempts.append((provider.name, str(exc)))
                if not exc.retryable:
                    raise
                # Emit a failover event when there's a next driver to
                # try. Skip on the LAST attempt — that's not a failover,
                # that's exhaustion (raises below).
                if self._on_failover is not None and i + 1 < len(self._providers):
                    next_provider = self._providers[i + 1]
                    try:
                        await self._on_failover(provider.name, next_provider.name, exc)
                    except Exception as cb_exc:  # pragma: no cover — best-effort
                        log.warning(
                            "router.failover_callback_failed",
                            error=f"{type(cb_exc).__name__}: {cb_exc}"[:200],
                        )
        raise NoDriversAvailable(attempts)

    async def aclose(self) -> None:
        for provider in self._providers:
            try:
                await provider.aclose()
            except Exception as exc:  # pragma: no cover — best-effort close
                log.warning("router.close_failed", provider=provider.name, error=str(exc))
