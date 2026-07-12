"""Engine — composes the middleware chain around the LLM/tool dispatch.

The engine is interface-agnostic: the CLI and the FastAPI HTTP surface
both drive the same ``run_turn`` entry point.

The innermost dispatch is a ``TurnDispatcher`` protocol — satisfied
either by a fake dispatcher in tests or a real provider implementation;
this module does not depend on which.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

import structlog

from agentix.core.middleware.base import Middleware, compose_chain, validate_order
from agentix.core.session import Session
from agentix.core.session import save as save_session
from agentix.core.types import Message, Turn
from agentix.drivers.session import bind_turn, unbind_turn
from agentix.storage import MinioStore, SqliteStore

log = structlog.get_logger(__name__)

TurnDispatcher = Callable[[Turn], Awaitable[Turn]]


class Engine:
    """Drives the ordered middleware chain for one session at a time."""

    def __init__(
        self,
        *,
        sqlite: SqliteStore,
        minio: MinioStore,
        middlewares: Sequence[Middleware],
        dispatcher: TurnDispatcher,
    ) -> None:
        validate_order(middlewares)
        self._sqlite = sqlite
        self._minio = minio
        self._middlewares = middlewares
        self._chain = compose_chain(middlewares, dispatcher)

    async def run_turn(
        self,
        session: Session,
        user_message: Message | None = None,
    ) -> Turn:
        """Advance ``session`` by one turn. Returns the resulting Turn.

        The session's ``messages`` list is updated in-place with the new
        user and assistant messages when the turn completes successfully.
        Aborted turns are recorded but don't extend the session history.
        """
        if user_message is not None:
            session.messages.append(user_message)

        # Snapshot the pre-turn message count so we can pick up the delta
        # the dispatcher added. Scripted dispatchers leave input_messages
        # untouched and set assistant_message; the AgentDispatcher
        # appends every assistant-with-tool_calls + tool_result message
        # directly into input_messages so the next LLM call sees the full
        # context. Both patterns round-trip through this same logic.
        pre_turn_len = len(session.messages)
        turn = Turn(
            session_id=session.id,
            customer_id=session.customer_id,
            turn_index=session.turn_index,
            input_messages=list(session.messages),
        )
        # Turn attribution: every nested driver call inside the chain (LLM,
        # vendor I/O) reads current_turn_id for log/usage attribution — the
        # per-turn counterpart of session_scope's session binding.
        turn_token = bind_turn(str(turn.turn_index))
        try:
            result = await self._chain(turn)
        finally:
            unbind_turn(turn_token)

        if result.status == "pending":
            # inner dispatch ran to completion without anybody changing status
            result.status = "ok"

        if result.status == "ok":
            # Delta from the dispatcher's modifications to input_messages.
            delta = result.input_messages[pre_turn_len:]
            if delta:
                session.messages.extend(delta)
            if result.assistant_message is not None and (not delta or delta[-1] is not result.assistant_message):
                session.messages.append(result.assistant_message)
        session.turn_index += 1

        if result.status in ("aborted", "error"):
            session.status = "paused" if result.status == "aborted" else "failed"

        # Agent dispatcher already saves per tool — skip the duplicate.
        if not result.checkpoint_saved_by_dispatcher:
            try:
                await save_session(
                    session,
                    sqlite=self._sqlite,
                    minio=self._minio,
                    checkpoint="latest",
                )
            except Exception as exc:
                log.warning(
                    "engine.checkpoint_latest_failed",
                    session_id=session.id,
                    turn_index=result.turn_index,
                    error=type(exc).__name__,
                    message=str(exc)[:500],
                )

        return result
