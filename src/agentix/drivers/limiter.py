"""Global driver capacity limiter (isolation.md I5).

Session-owned state is per-task, but *shared external capacity* — the concurrent
model calls the whole process may have in flight — is intentionally governed by one
process-global limiter, not per-session. Without it, ``gather``-over-Sessions (or
multi-agent fan-out) would multiply concurrent upstream calls by the number of
live sessions and trip provider rate limits / exhaust sockets.

The limiter is a single semaphore acquired around every driver I/O call
(chat ``complete``, embedding ``embed``, stt ``transcribe``). It is keyed by
running event loop so it is safe to reuse across test loops (each loop gets its
own instance) while remaining a single shared gate within the one loop a
production worker runs — the "global" scope that matters. Per-type / per-driver
limits are DIRECTION (``docs/drivers.md``).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

# Default max concurrent external model calls per process. Conservative — one
# single-tenant worker rarely needs more, and it caps fan-out storms. Override
# with ``configure_driver_capacity`` at startup (e.g. from config/env).
_DEFAULT_LIMIT = 8

_limit = _DEFAULT_LIMIT
# One semaphore per event loop (id(loop) -> semaphore). Keying by loop avoids
# reusing a semaphore bound to a finished loop across asyncio.run() boundaries.
_semaphores: dict[int, asyncio.Semaphore] = {}


def configure_driver_capacity(limit: int) -> None:
    """Set the process-global concurrent-model-call ceiling. Call once at startup,
    before the loop does real work. Rebuilds existing per-loop semaphores lazily."""
    global _limit
    if limit < 1:
        raise ValueError("driver capacity limit must be >= 1")
    _limit = limit
    _semaphores.clear()


def current_limit() -> int:
    """The configured ceiling (for introspection / tests)."""
    return _limit


def _semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    key = id(loop)
    sem = _semaphores.get(key)
    if sem is None:
        sem = asyncio.Semaphore(_limit)
        _semaphores[key] = sem
    return sem


@contextlib.asynccontextmanager
async def driver_capacity() -> AsyncIterator[None]:
    """Acquire one slot of global driver capacity for the duration of the block.

    Wrap every external model call in this. When all slots are taken, additional
    callers await here rather than piling concurrent requests onto the upstream.
    """
    async with _semaphore():
        yield
