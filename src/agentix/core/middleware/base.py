"""Middleware protocol and chain composer.

The chain runs turn-in, turn-out. Each middleware may:
  * inspect/mutate the ``Turn`` before forwarding it,
  * await ``next_(turn)`` to drive the rest of the chain,
  * inspect/mutate the ``Turn`` after the downstream call returns,
  * or skip the downstream call entirely (e.g. SafetyGate on a dry-run).

``MIDDLEWARE_ORDER`` is the single source of truth for the ordering the
engine assembles — tested as an invariant.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol, runtime_checkable

from agentix.core.types import Turn

Next = Callable[[Turn], Awaitable[Turn]]


@runtime_checkable
class Middleware(Protocol):
    """Single layer in the ordered chain."""

    name: str

    async def __call__(self, turn: Turn, next_: Next) -> Turn: ...


# The order is load-bearing. Do NOT reorder without an architectural
# change.
MIDDLEWARE_ORDER: tuple[str, ...] = (
    "TrajectoryCapture",
    "CostTracking",
    "TokenBudget",
    "ToolCallCountCap",  #: per-tool thrash circuit breaker
    "LoopDetection",
    "Retry",
    "DanglingToolCall",
    "SafetyGate",
    "MemoryMaintain",
)


def compose_chain(middlewares: Sequence[Middleware], inner: Next) -> Next:
    """Compose middlewares outside-in around ``inner``.

    ``middlewares[0]`` becomes the outermost wrapper. The resulting
    callable may be awaited on a ``Turn`` to drive the entire stack.
    """
    chain: Next = inner
    for mw in reversed(middlewares):
        chain = _wrap(mw, chain)
    return chain


def _wrap(mw: Middleware, downstream: Next) -> Next:
    async def wrapped(turn: Turn) -> Turn:
        return await mw(turn, downstream)

    return wrapped


def validate_order(middlewares: Sequence[Middleware]) -> None:
    """Enforce that ``middlewares`` matches ``MIDDLEWARE_ORDER`` exactly.

    Allowed: the list may be a *prefix* of ``MIDDLEWARE_ORDER`` (e.g. a
    test that only installs Trajectory + Cost + Budget). Disallowed: any
    other permutation. The engine calls this in ``__init__``.
    """
    names = tuple(mw.name for mw in middlewares)
    expected = MIDDLEWARE_ORDER[: len(names)]
    if names != expected:
        raise ValueError(f"middleware order mismatch:\n got: {names}\n expected: {expected}")
