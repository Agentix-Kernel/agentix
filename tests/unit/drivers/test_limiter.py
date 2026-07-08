"""Global LLM capacity limiter (isolation.md I5 / agentix#40)."""

from __future__ import annotations

import asyncio

import pytest

from agentix.drivers.limiter import (
    configure_driver_capacity,
    current_limit,
    driver_capacity,
)


def test_default_and_configure() -> None:
    configure_driver_capacity(8)  # restore default for isolation
    assert current_limit() == 8
    configure_driver_capacity(3)
    assert current_limit() == 3
    with pytest.raises(ValueError):
        configure_driver_capacity(0)
    configure_driver_capacity(8)


@pytest.mark.asyncio
async def test_bounds_concurrency() -> None:
    """No more than ``limit`` blocks run concurrently; extra callers wait."""
    configure_driver_capacity(2)
    try:
        live = 0
        peak = 0
        lock = asyncio.Lock()

        async def worker() -> None:
            nonlocal live, peak
            async with driver_capacity():
                async with lock:
                    live += 1
                    peak = max(peak, live)
                await asyncio.sleep(0.02)
                async with lock:
                    live -= 1

        await asyncio.gather(*(worker() for _ in range(8)))
        assert peak <= 2
        assert peak >= 1
    finally:
        configure_driver_capacity(8)


@pytest.mark.asyncio
async def test_slot_released_on_exception() -> None:
    """A raising body still releases its slot (context manager guarantees it)."""
    configure_driver_capacity(1)
    try:
        with pytest.raises(RuntimeError):
            async with driver_capacity():
                raise RuntimeError("boom")
        # If the slot leaked, this second acquire would hang; wrap in a timeout.
        async with asyncio.timeout(1):
            async with driver_capacity():
                pass
    finally:
        configure_driver_capacity(8)
