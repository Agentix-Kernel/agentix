"""Integration-sized tests for SqliteStore — real file, WAL, 1000-turn FTS."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from agentix.storage import SqliteStore

pytestmark = [pytest.mark.integration, pytest.mark.stress]


@pytest.mark.asyncio
async def test_stress_1000_turns_fts_latency(tmp_path: Path) -> None:
    """Insert 1000 turns with varied content; FTS should return hits in <250ms."""
    store = SqliteStore(tmp_path / "stress.db")
    await store.initialize()
    try:
        await store.create_session(session_id="S", customer_id="example")
        # Build 1000 varied inserts so FTS has a realistic index.
        # Each turn references one of 10 fictitious Odoo models so FTS has
        # meaningful partitions.
        models = [
            "res.partner",
            "sale.order",
            "sale.order.line",
            "account.move",
            "account.move.line",
            "product.template",
            "product.product",
            "stock.picking",
            "hr.employee",
            "ir.translation",
        ]
        await asyncio.gather(
            *(
                store.append_turn(
                    session_id="S",
                    turn_index=i,
                    role="assistant",
                    content_inline=f"migrating {models[i % len(models)]} batch {i} ok",
                    tool_name="extract_from_odoo",
                )
                for i in range(1000)
            )
        )
        # FTS search latency
        t0 = time.monotonic()
        results = await store.search_turns("sale.order.line", limit=20)
        elapsed_ms = (time.monotonic() - t0) * 1000
        # Every hit should contain the phrase
        assert all("sale.order.line" in r["content_inline"] for r in results)
        # FTS over 1000 rows should easily clear 250ms.
        assert elapsed_ms < 250, f"FTS search took {elapsed_ms:.0f}ms on 1000 rows"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_stress_concurrent_writers_wal(tmp_path: Path) -> None:
    """Many tasks appending turns + safety events + errors simultaneously."""
    store = SqliteStore(tmp_path / "concurrent.db")
    await store.initialize()
    try:
        await store.create_session(session_id="S", customer_id="example")

        async def one_writer(i: int) -> None:
            turn_id = await store.append_turn(
                session_id="S",
                turn_index=i,
                role="tool",
                tool_name="load_to_odoo",
                content_inline=f"batch-{i}",
            )
            if i % 7 == 0:
                await store.append_safety_event(
                    session_id="S",
                    type="per_batch_verify_fail",
                    turn_id=turn_id,
                    detail=f"mismatch on batch {i}",
                )
            if i % 13 == 0:
                await store.append_error(
                    session_id="S",
                    error_class="TransientError",
                    error_message=f"boom at {i}",
                    turn_id=turn_id,
                )

        await asyncio.gather(*(one_writer(i) for i in range(100)))

        db = store._conn()
        async with db.execute("SELECT COUNT(*) FROM turns") as cur:
            row = await cur.fetchone()
        assert row is not None and row[0] == 100
        # 100 / 7 = 14 safety events (i=0, 7, 14, ..., 98)
        assert await store.count_safety_events("S") == 15
    finally:
        await store.close()
