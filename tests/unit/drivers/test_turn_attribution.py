"""Turn attribution (agentix#86) — the engine binds ``current_turn_id`` around
the middleware chain so every nested driver call inside a turn can attribute
its logs/usage. Mirrors session attribution one level down; vendor drivers
READ the ContextVar, they never define their own.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from agentix.core.engine import Engine
from agentix.core.session import Session
from agentix.core.types import Message, Turn
from agentix.drivers.session import bind_turn, current_turn_id, unbind_turn


def test_bind_unbind_turn_roundtrip() -> None:
    assert current_turn_id.get() is None
    token = bind_turn("7")
    assert current_turn_id.get() == "7"
    unbind_turn(token)
    assert current_turn_id.get() is None


def test_bind_turn_nests_and_restores() -> None:
    outer = bind_turn("1")
    inner = bind_turn("2")
    assert current_turn_id.get() == "2"
    unbind_turn(inner)
    assert current_turn_id.get() == "1"
    unbind_turn(outer)
    assert current_turn_id.get() is None


@pytest.mark.asyncio
async def test_engine_binds_turn_id_around_chain() -> None:
    """The dispatcher (innermost chain element) must observe the turn id of
    the turn it is running, and the binding must not leak past run_turn."""
    seen: list[str | None] = []

    async def dispatcher(turn: Turn) -> Turn:
        seen.append(current_turn_id.get())
        # Skip the engine's checkpoint save — no stores in this test.
        turn.checkpoint_saved_by_dispatcher = True
        turn.assistant_message = Message(role="assistant", content="ok")
        return turn

    engine = Engine(
        sqlite=cast(Any, None),
        minio=cast(Any, None),
        middlewares=[],
        dispatcher=dispatcher,
    )
    session = Session(customer_id="c1", turn_index=3)

    await engine.run_turn(session, Message(role="user", content="hi"))

    assert seen == ["3"]
    assert current_turn_id.get() is None  # unbound after the turn
    assert session.turn_index == 4
