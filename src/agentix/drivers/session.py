"""Session binding for driver calls — modality-agnostic ContextVar.

The agent runner binds the session id at session start so every nested
driver call inside that scope attributes usage/cost to the right session.
Chat cost recording (``drivers/cost.py``) is the primary consumer; other
driver types read it for log attribution.
"""

from __future__ import annotations

import contextvars
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentix.drivers.registry import DriverRegistry

# ContextVar threading: default None = no session bound (e.g. CLI-level
# probes that aren't part of a tracked run).
current_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "agentix.drivers.current_session_id", default=None
)

# Turn attribution mirrors session attribution one level down: the engine
# binds the turn identity (the session's turn_index, stringified) around the
# middleware chain, so every nested driver call inside that turn can log it.
# Vendor drivers READ this var; they never define their own.
current_turn_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "agentix.drivers.current_turn_id", default=None
)


def bind_turn(turn_id: str) -> contextvars.Token[str | None]:
    """Bind ``turn_id`` for the current task; pass the returned token to
    :func:`unbind_turn` to restore. The engine calls this per turn."""
    return current_turn_id.set(turn_id)


def unbind_turn(token: contextvars.Token[str | None]) -> None:
    current_turn_id.reset(token)


def bind_session(session_id: str) -> contextvars.Token[str | None]:
    """Bind ``session_id`` to the driver contextvar for the current task.

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

    Passing ``registry=`` additionally drains any driver leases still open
    for this session at scope exit (the leak backstop of the seam-#13 lease
    path — the lease context manager remains the primary lifetime).
    """

    def __init__(self, session_id: str, *, registry: DriverRegistry | None = None) -> None:
        self._session_id = session_id
        self._registry = registry
        self._token: contextvars.Token[str | None] | None = None

    async def __aenter__(self) -> session_scope:
        self._token = bind_session(self._session_id)
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        if self._registry is not None:
            await self._registry.aclose_session_leases(self._session_id)
        if self._token is not None:
            unbind_session(self._token)
            self._token = None
