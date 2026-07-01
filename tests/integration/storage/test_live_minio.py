"""Integration tests against a live MinIO.

Brought up via:
    docker compose -f tests/fixtures/docker-compose.minio.yml up -d

Tests auto-skip if no MinIO reachable at ``LUDO_TEST_MINIO_ENDPOINT``
(default ``localhost:19000``).
"""

from __future__ import annotations

import asyncio
import os
import socket
import time
import uuid
from collections.abc import AsyncIterator

import pytest

from agentix.storage import MinioConfig, MinioStore

pytestmark = [pytest.mark.integration]


def _endpoint() -> str:
    return os.environ.get("LUDO_TEST_MINIO_ENDPOINT", "localhost:19000")


def _fixture_up() -> bool:
    host, _, port = _endpoint().partition(":")
    try:
        with socket.create_connection((host, int(port or "9000")), timeout=1):
            return True
    except OSError:
        return False


@pytest.fixture(autouse=True)
def _guard() -> None:
    if not _fixture_up():
        pytest.skip(f"MinIO not reachable at {_endpoint()}")


def _store(bucket: str) -> MinioStore:
    return MinioStore(
        MinioConfig(
            endpoint=_endpoint(),
            access_key=os.environ.get("LUDO_TEST_MINIO_ACCESS_KEY", "ludo"),
            secret_key=os.environ.get("LUDO_TEST_MINIO_SECRET_KEY", "ludo-dev-password"),
            bucket=bucket,
            secure=False,
        )
    )


@pytest.fixture
async def store() -> AsyncIterator[MinioStore]:
    bucket = f"ludo-test-{uuid.uuid4().hex[:8]}"
    s = _store(bucket)
    await s.ensure_bucket()
    try:
        yield s
    finally:
        # Best-effort cleanup: list + delete every object, then the bucket.
        keys = await s.list_objects()
        for key in keys:
            await s.delete_object(key)


@pytest.mark.asyncio
async def test_live_put_get_bytes_round_trip(store: MinioStore) -> None:
    await store.put_bytes("hello.bin", b"hello-world")
    assert await store.get_bytes("hello.bin") == b"hello-world"


@pytest.mark.asyncio
async def test_live_put_get_json(store: MinioStore) -> None:
    payload = {"model": "res.partner", "count": 1745}
    await store.put_json("checkpoint.json", payload)
    got = await store.get_json("checkpoint.json")
    assert got == payload


@pytest.mark.asyncio
async def test_live_put_get_jsonl(store: MinioStore) -> None:
    rows = [{"id": i, "name": f"partner-{i}"} for i in range(50)]
    await store.put_jsonl("extract.jsonl", rows)
    raw = await store.get_bytes("extract.jsonl")
    lines = [line for line in raw.split(b"\n") if line]
    assert len(lines) == 50


@pytest.mark.asyncio
async def test_live_stream_round_trip(store: MinioStore) -> None:
    async def producer() -> AsyncIterator[bytes]:
        for _ in range(16):
            yield b"x" * 4096

    await store.put_stream("big.bin", producer())
    got = b""
    async for chunk in store.get_stream("big.bin", chunk_size=8192):
        got += chunk
    assert len(got) == 16 * 4096
    assert got == b"x" * (16 * 4096)


@pytest.mark.asyncio
async def test_live_list_and_delete(store: MinioStore) -> None:
    for i in range(5):
        await store.put_bytes(f"blobs/item-{i}.bin", str(i).encode())
    keys = await store.list_objects("blobs/")
    assert len(keys) == 5
    await store.delete_object("blobs/item-2.bin")
    assert "blobs/item-2.bin" not in await store.list_objects("blobs/")


@pytest.mark.asyncio
async def test_live_exists(store: MinioStore) -> None:
    assert await store.exists("ghost") is False
    await store.put_bytes("present", b"x")
    assert await store.exists("present") is True


@pytest.mark.asyncio
async def test_live_stress_concurrent_uploads(store: MinioStore) -> None:
    """100-way concurrent uploads should all land and round-trip intact."""
    N = 100
    t0 = time.monotonic()
    await asyncio.gather(*(store.put_bytes(f"concurrent/obj-{i:03d}.bin", f"payload-{i}".encode()) for i in range(N)))
    elapsed = time.monotonic() - t0
    keys = await store.list_objects("concurrent/")
    assert len(keys) == N
    # sample a few for integrity
    samples = await asyncio.gather(
        store.get_bytes("concurrent/obj-001.bin"),
        store.get_bytes("concurrent/obj-050.bin"),
        store.get_bytes("concurrent/obj-099.bin"),
    )
    assert list(samples) == [b"payload-1", b"payload-50", b"payload-99"]
    assert elapsed < 60, f"100 uploads took {elapsed:.1f}s (MinIO too slow?)"
