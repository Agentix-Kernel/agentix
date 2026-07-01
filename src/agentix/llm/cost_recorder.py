"""Cost recording at the LLM-call boundary.

Cost is recorded where money is spent — inside the LLM provider's
``complete()`` call, immediately after the upstream returns. Recording
at the turn boundary instead would be a **silent budget breach**: when
the inner agent loop raises mid-turn (tool error, validation failure,
dispatcher exception) the unwound chain skips any turn-level recording
line, yet the LLM call already returned with tokens billed upstream. A
runaway model could emit 100k tokens, the turn abort on a tool error,
and the per-model cap never fire because the cap reads from SQLite,
which never received the increment.

Design:

* :class:`CostRecordingProvider` decorates any :class:`Provider`.
* Each ``complete()`` call: invoke inner provider, then if the response
  carries non-zero token usage AND a session id is set in
  contextvar, persist ``(input_tokens, output_tokens, cost_usd)`` to
  SQLite via ``update_session(cost_usd_delta=…, …)``.
* If the inner provider raises (no response, no billing), nothing is
  recorded — correct behaviour, the call wasn't billed.
* Session id flows via :data:`current_session_id` (a ContextVar so
  multiple concurrent sessions in tests don't cross-contaminate).

The CostTracking middleware retains a useful telemetry role
(turn-level aggregation, cache-read ratio) but no longer writes to
SQLite — that responsibility moved here.
"""

from __future__ import annotations

import contextvars
from typing import TYPE_CHECKING

import structlog

from agentix.core.middleware.cost_tracking import (
    FALLBACK_PRICING,
    ModelPricing,
    compute_cost_usd,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from agentix.llm.base import LlmRequest, LlmResponse, Provider
    from agentix.storage import SqliteStore

log = structlog.get_logger(__name__)


# ContextVar threading: the agent runner sets this at session start so
# every nested ``provider.complete()`` call inside that scope records
# against the right session. Default None = no session bound (e.g.
# CLI-level probes that aren't part of a tracked migration).
current_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "agentix.llm.current_session_id", default=None
)


class CostRecordingProvider:
    """Wraps a :class:`Provider`. Records cost+tokens immediately on each
    successful ``complete()`` call.

    Implements the Provider protocol verbatim — the ``ProviderRouter``
    or any other caller can swap a wrapped provider for an unwrapped
    one without code changes.
    """

    def __init__(
        self,
        inner: Provider,
        *,
        sqlite: SqliteStore,
        pricing_table: Mapping[str, ModelPricing] = FALLBACK_PRICING,
    ) -> None:
        self._inner = inner
        self._sqlite = sqlite
        self._pricing = pricing_table

    @property
    def name(self) -> str:
        # Forward the inner provider's name verbatim so the
        # ProviderRouter's failover telemetry stays accurate.
        return self._inner.name

    @property
    def default_model(self) -> str:
        return self._inner.default_model

    async def complete(self, request: LlmRequest) -> LlmResponse:
        """Call the inner provider; on success, persist cost to SQLite.

        Cost recording is **best-effort**. A SQLite write failure logs a
        warning but doesn't propagate — we don't want a transient DB
        issue to mask the LLM response from the caller.

        ``current_session_id`` ContextVar must be set by the caller
        (typically at agent session start). When unset, the provider
        still works but cost is not recorded — useful for CLI probes
        and unit tests that don't need the SQLite side effect.
        """
        response = await self._inner.complete(request)
        if response.usage.total == 0:
            return response

        session_id = current_session_id.get()
        if session_id is None:
            # A real LLM call billed the upstream but no session is
            # bound — those tokens are invisible to TokenBudget /
            # per-customer cost cap, and disappear from per-model
            # attribution. Any entry point that fires LLM calls outside
            # a session_scope() leaks like this. Log loud so regressions
            # are spotted by the operator instead of by a post-mortem.
            log.warning(
                "cost_recorder.no_session_id_in_context",
                provider=self._inner.name,
                model=response.model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                cached_tokens=response.usage.cached_tokens,
                hint=(
                    "wrap the calling code in `async with session_scope(id):` "
                    "or call `bind_session(id)` before invoking the provider"
                ),
            )
            return response

        # Source-of-truth preference for cost:
        #   1. response.raw["cost_usd"] — the upstream's actual billed
        #      amount (HUBLE forwards this from melious / its own gateway
        #      logic). Preferring it makes SQLite cost match the bill
        #      exactly for any provider that reports it.
        #   2. compute_cost_usd() — locally-derived estimate using
        #      FALLBACK_PRICING. Used when the upstream doesn't return
        #      a cost (anthropic / openai direct) OR for models
        #      not yet in the pricing table (estimate via __unknown__
        #      fallback — known under-/over-counting; flagged for
        #      operator awareness in FALLBACK_PRICING).
        cost = _extract_real_cost(response) or compute_cost_usd(
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cached_tokens=response.usage.cached_tokens,
            pricing_table=self._pricing,
        )
        try:
            await self._sqlite.update_session(
                session_id,
                input_tokens_delta=response.usage.input_tokens,
                output_tokens_delta=response.usage.output_tokens,
                cost_usd_delta=cost,
            )
        except Exception as exc:
            # SQLite failure must not break the LLM round-trip. We log
            # loudly so it surfaces in operator logs; the cost gap will
            # be spotted in the per-session summary.
            log.warning(
                "cost_recorder.persist_failed",
                session_id=session_id,
                provider=self._inner.name,
                model=response.model,
                cost_usd=round(cost, 6),
                error=str(exc)[:160],
            )
            return response

        log.debug(
            "cost_recorder.recorded",
            session_id=session_id,
            provider=self._inner.name,
            model=response.model,
            cost_usd=round(cost, 6),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cached_tokens=response.usage.cached_tokens,
        )
        return response

    async def aclose(self) -> None:
        """Forward shutdown to the inner provider."""
        if hasattr(self._inner, "aclose"):
            await self._inner.aclose()


def _extract_real_cost(response: LlmResponse) -> float | None:
    """Pull the upstream-reported billed cost from response.raw, if any.

    Returns the cost as a float when present and a positive number;
    None otherwise (so the caller falls back to local computation).

    HUBLE writes ``raw["cost_usd"]`` on every response. Other providers
    (anthropic / openai direct) don't, so this returns None and the
    caller uses compute_cost_usd. Conservative on type: rejects 0,
    negatives, NaN, and non-numeric so a malformed upstream payload
    can't suppress local-fallback accounting.
    """
    raw = getattr(response, "raw", None)
    if not isinstance(raw, dict):
        return None
    val = raw.get("cost_usd")
    if val is None:
        return None
    try:
        cost = float(val)
    except (TypeError, ValueError):
        return None
    # Reject non-finite / non-positive values — treat as "no real cost
    # reported" and let the local fallback fire.
    if cost <= 0 or cost != cost:  # cost != cost catches NaN
        return None
    return cost


def bind_session(session_id: str) -> contextvars.Token[str | None]:
    """Bind ``session_id`` to the LLM contextvar for the current task.

    Returns a ``Token`` the caller passes to :func:`unbind_session` to
    restore the previous value. Typical use:

    .. code:: python

        token = bind_session(session.id)
        try:
            await run_agent_session(...)
        finally:
            unbind_session(token)

    Or use the async-with helper :func:`session_scope`.
    """
    return current_session_id.set(session_id)


def unbind_session(token: contextvars.Token[str | None]) -> None:
    current_session_id.reset(token)


class session_scope:
    """Async context manager: bind a session id for the duration of the
    ``async with`` block. Exits restore the prior contextvar value.

    .. code:: python

        async with session_scope(session.id):
            await run_agent_session(...)
    """

    def __init__(self, session_id: str) -> None:
        self._session_id = session_id
        self._token: contextvars.Token[str | None] | None = None

    async def __aenter__(self) -> session_scope:
        self._token = bind_session(self._session_id)
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        if self._token is not None:
            unbind_session(self._token)
            self._token = None
