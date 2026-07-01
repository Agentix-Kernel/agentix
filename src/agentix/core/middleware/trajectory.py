"""TrajectoryCapture — the outermost middleware.

Mirrors every turn to two places:

* **MinIO**, as one object per turn under
  ``blobs/{customer_id}/trajectories/{session_id}/turn-{turn_index:06d}.json``.
  One object per turn avoids a read-modify-write append to a single
  JSONL blob, which would make every Nth turn transfer N*(N+1)/2 bytes
  to MinIO and silently last-writer-wins on concurrent writers.
* **SQLite**, as a row in ``turns`` — the operational index used by the
  dashboard and FTS search.

Wrapping outermost guarantees we capture errors raised by inner
middlewares. Exceptions are logged as ``role='tool'`` rows with
``tool_ok=False``, re-raised for upstream handling.
"""

from __future__ import annotations

import json

import structlog

from agentix.core.middleware.base import Next
from agentix.core.types import Message, Turn
from agentix.storage import MinioStore, SqliteStore

log = structlog.get_logger(__name__)


class TrajectoryCaptureMiddleware:
    """Records every turn to MinIO + SQLite."""

    name = "TrajectoryCapture"

    def __init__(self, *, sqlite: SqliteStore, minio: MinioStore) -> None:
        self._sqlite = sqlite
        self._minio = minio

    async def __call__(self, turn: Turn, next_: Next) -> Turn:
        turn.mark_started()
        try:
            result = await next_(turn)
        except Exception as exc:
            turn.mark_error(type(exc).__name__, str(exc))
            turn.mark_finished()
            await self._persist(turn)
            raise
        result.mark_finished()
        await self._persist(result)
        return result

    async def _persist(self, turn: Turn) -> None:
        # 1. SQLite — operational index for each user / assistant / tool msg.
        await self._persist_sqlite(turn)
        # 2. MinIO — append a JSONL line for trajectory training data.
        await self._append_jsonl(turn)

    async def _persist_sqlite(self, turn: Turn) -> None:
        # Record every input message (user + earlier tool results) — but
        # only the ones added this turn. We persist only the *new*
        # content: the trailing user/tool messages and the assistant
        # reply if present.
        if turn.input_messages:
            last_user = _last_non_assistant(turn.input_messages)
            if last_user is not None and last_user.role in ("user", "tool"):
                await self._sqlite.append_turn(
                    session_id=turn.session_id,
                    turn_index=turn.turn_index,
                    role=last_user.role,
                    content_inline=last_user.content or None,
                )

        if turn.assistant_message is not None:
            await self._sqlite.append_turn(
                session_id=turn.session_id,
                turn_index=turn.turn_index,
                role="assistant",
                content_inline=turn.assistant_message.content or None,
                latency_ms=turn.elapsed_ms,
                input_tokens=turn.usage.input_tokens,
                output_tokens=turn.usage.output_tokens,
                cost_usd=turn.cost_usd,
            )

        # AgentDispatcher writes tool rows per-iteration; here we only
        # write the tail (scripted dispatchers leave it all).
        for tool_result in turn.tool_call_results[turn.persisted_tool_count :]:
            await self._sqlite.append_turn(
                session_id=turn.session_id,
                turn_index=turn.turn_index,
                role="tool",
                tool_name=tool_result.tool_name,
                tool_ok=tool_result.ok,
                latency_ms=tool_result.latency_ms,
                content_inline=json.dumps(tool_result.output) if tool_result.output is not None else None,
            )

    async def _append_jsonl(self, turn: Turn) -> None:
        """Write this turn as its own MinIO object.

        No read-modify-write: a 500-turn session writes 500 small objects
        instead of re-transferring 500*(500+1)/2 turns of cumulative
        JSONL. Concurrent writers on the same session append to distinct
        keys (one per turn_index) so no race, no silent loss.
        """
        key = MinioStore.key_trajectory(turn.customer_id, turn.session_id, turn.turn_index)
        body = json.dumps(turn.model_dump(mode="json"), ensure_ascii=False).encode("utf-8")
        await self._minio.put_bytes(key, body, content_type="application/json")


async def list_trajectory_turns(minio: MinioStore, customer_id: str, session_id: str) -> list[str]:
    """Return the session's turn-blob keys in chronological order.

    Callers: replay tooling, training-data export, any operator reading
    the trajectory through the HTTP API. The key scheme is
    lexicographically ordered by turn_index, so a plain
    ``list_objects(prefix)`` with sorted output is sufficient.
    """
    prefix = MinioStore.prefix_trajectories(customer_id, session_id)
    keys = await minio.list_objects(prefix)
    return sorted(keys)


def _last_non_assistant(messages: list[Message]) -> Message | None:
    for message in reversed(messages):
        if message.role != "assistant":
            return message
    return None
