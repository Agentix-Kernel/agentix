"""LocalObjectStoreDriver (#92) — filesystem object transport.

Real-tmp-dir tests: protocol conformance, verb semantics (S3-idempotent
delete, prefix listing, stream chunking), path containment, and the
documented presigned_get degradation (file:// URI).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentix.drivers.adapters.intrinsic.local_fs_object import LocalObjectStoreDriver
from agentix.drivers.base import DriverInvalidRequest
from agentix.drivers.object_store import ObjectNotFound, ObjectStoreDriver
from agentix.storage import MinioStore


@pytest.fixture
def driver(tmp_path: Path) -> LocalObjectStoreDriver:
    return LocalObjectStoreDriver(tmp_path / "objects")


def test_protocol_conformance(driver: LocalObjectStoreDriver) -> None:
    assert isinstance(driver, ObjectStoreDriver)
    d = driver.descriptor
    assert (d.type, d.modality, d.source) == ("storage", "object", "local")


def test_empty_root_rejected() -> None:
    with pytest.raises(DriverInvalidRequest):
        LocalObjectStoreDriver("")


@pytest.mark.asyncio
async def test_put_get_roundtrip_and_exists(driver: LocalObjectStoreDriver) -> None:
    await driver.ensure_bucket()
    key = "blobs/c1/checkpoints/s_1/latest.json"
    assert not await driver.exists(key)
    await driver.put_bytes(key, b'{"x": 1}')
    assert await driver.exists(key)
    assert await driver.get_bytes(key) == b'{"x": 1}'


@pytest.mark.asyncio
async def test_get_missing_raises_object_not_found(driver: LocalObjectStoreDriver) -> None:
    with pytest.raises(ObjectNotFound):
        await driver.get_bytes("nope/missing.bin")


@pytest.mark.asyncio
async def test_put_file_and_copy(driver: LocalObjectStoreDriver, tmp_path: Path) -> None:
    source = tmp_path / "upload.txt"
    source.write_bytes(b"payload")
    await driver.put_file("a/original.txt", str(source))
    await driver.copy_object("a/original.txt", "b/copy.txt")
    assert await driver.get_bytes("b/copy.txt") == b"payload"
    with pytest.raises(ObjectNotFound):
        await driver.copy_object("a/missing.txt", "b/x.txt")


@pytest.mark.asyncio
async def test_list_objects_prefix_sorted_and_nonrecursive(driver: LocalObjectStoreDriver) -> None:
    for key in ("p/z.txt", "p/a.txt", "p/sub/deep.txt", "q/other.txt"):
        await driver.put_bytes(key, b"1")
    assert await driver.list_objects("p/") == ["p/a.txt", "p/sub/deep.txt", "p/z.txt"]
    assert await driver.list_objects("p/", recursive=False) == ["p/a.txt", "p/z.txt"]
    assert await driver.list_objects() == ["p/a.txt", "p/sub/deep.txt", "p/z.txt", "q/other.txt"]


@pytest.mark.asyncio
async def test_delete_is_idempotent(driver: LocalObjectStoreDriver) -> None:
    await driver.put_bytes("gone.bin", b"1")
    await driver.delete_object("gone.bin")
    assert not await driver.exists("gone.bin")
    await driver.delete_object("gone.bin")  # S3 semantics: no error


@pytest.mark.asyncio
async def test_get_stream_chunks(driver: LocalObjectStoreDriver) -> None:
    payload = bytes(range(256)) * 10
    await driver.put_bytes("stream.bin", payload)
    chunks = [chunk async for chunk in driver.get_stream("stream.bin", chunk_size=100)]
    assert all(len(c) <= 100 for c in chunks)
    assert b"".join(chunks) == payload


@pytest.mark.asyncio
async def test_presigned_get_is_file_uri(driver: LocalObjectStoreDriver) -> None:
    await driver.put_bytes("signed.txt", b"x")
    uri = await driver.presigned_get("signed.txt", download_name="ignored.txt")
    assert uri.startswith("file://") and uri.endswith("/signed.txt")
    with pytest.raises(ObjectNotFound):
        await driver.presigned_get("missing.txt")


@pytest.mark.asyncio
async def test_key_escape_rejected(driver: LocalObjectStoreDriver) -> None:
    for key in ("../outside.txt", "a/../../outside.txt", ""):
        with pytest.raises(DriverInvalidRequest):
            await driver.put_bytes(key, b"1")


@pytest.mark.asyncio
async def test_minio_store_composes_on_local_driver(tmp_path: Path) -> None:
    """The kernel blob layer runs unchanged over the local transport."""
    store = MinioStore(driver=LocalObjectStoreDriver(tmp_path / "objects"))
    await store.ensure_bucket()
    key = MinioStore.key_checkpoint("c1", "s_abc", "latest")
    await store.put_json(key, {"messages": [], "turn_index": 0})
    assert await store.get_json(key) == {"messages": [], "turn_index": 0}
