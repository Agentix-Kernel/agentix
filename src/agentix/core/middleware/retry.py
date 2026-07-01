"""Retry middleware — bounded exponential backoff over provider failures.

Wraps the LLM call with a jittered retry loop. Retries *only* on provider
errors the router already classified as retryable
(``LlmRateLimit`` / ``LlmUnavailable``); ``LlmInvalidRequest`` bails out
immediately. Tool failures are *not* retried here — tools own their own
retry configs.
"""

from __future__ import annotations

import asyncio
import random

import structlog

from agentix.core.middleware.base import Next
from agentix.core.types import Turn
from agentix.llm.base import LlmError, LlmInvalidRequest

log = structlog.get_logger(__name__)

# L6: intentionally smaller than ``OdooClient.DEFAULT_MAX_ATTEMPTS=5``.
# An LLM call is idempotent and cheap to retry, but a retryable provider
# error (rate limit, upstream 5xx) is a signal the provider is struggling
# — a third retry is unlikely to succeed where the second didn't. Odoo
# retries tolerate more because they're a JSON-RPC transport concern,
# not a busy-provider signal.
_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_BASE_DELAY = 0.5
_DEFAULT_MAX_DELAY = 15.0


class RetryMiddleware:
    """Retries the LLM call on retryable provider errors."""

    name = "Retry"

    def __init__(
        self,
        *,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        base_delay_s: float = _DEFAULT_BASE_DELAY,
        max_delay_s: float = _DEFAULT_MAX_DELAY,
    ) -> None:
        self._max_attempts = max_attempts
        self._base_delay = base_delay_s
        self._max_delay = max_delay_s

    async def __call__(self, turn: Turn, next_: Next) -> Turn:
        for attempt in range(1, self._max_attempts + 1):
            try:
                return await next_(turn)
            except LlmInvalidRequest:
                # Non-retryable — pass straight through.
                raise
            except LlmError as e:
                if not e.retryable or attempt >= self._max_attempts:
                    raise
                window = min(self._max_delay, self._base_delay * (2 ** (attempt - 1)))
                delay = random.uniform(0.0, window)
                log.warning(
                    "retry.llm",
                    turn=turn.turn_index,
                    attempt=attempt,
                    max_attempts=self._max_attempts,
                    delay_s=round(delay, 3),
                    provider=e.provider,
                    error=str(e),
                )
                await asyncio.sleep(delay)
        # Unreachable — every path above either returns or re-raises.
        # The branch on attempt >= max_attempts re-raises instead of
        # falling through to a subsequent iteration, so loop exit
        # without outcome is impossible. Assert rather than fabricate a
        # RuntimeError that a reader might mistake for a real code path.
        raise AssertionError("retry loop exited without outcome — unreachable")
