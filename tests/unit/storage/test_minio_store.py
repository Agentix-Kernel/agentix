"""Unit tests for MinioStore — mocked minio.Minio.

Since v0.5.1 the raw client lives in the MinioObjectStoreDriver
(``drivers/adapters/minio.py``); ``MinioStore(config)`` builds it
internally, so these tests double as delegation-parity proof: the
assertions are unchanged from the pre-driver split."""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import MagicMock, patch

import pytest

from agentix.storage import MinioConfig, MinioStore


def _config() -> MinioConfig:
    return MinioConfig(endpoint="minio:9000", access_key="k", secret_key="s", bucket="ludo")


@pytest.fixture
def mock_minio() -> tuple[MinioStore, MagicMock]:
    with patch("agentix.drivers.adapters.minio.Minio") as minio_cls:
        client = MagicMock()
        minio_cls.return_value = client
        store = MinioStore(_config())
        return store, client


# ──────────────────────────────── key helpers ──────────────────────────────


def test_key_checkpoint_format() -> None:
    assert (
        MinioStore.key_checkpoint("acme", "s", "extract_complete") == "blobs/acme/checkpoints/s/extract_complete.json"
    )


def test_key_session_artifact_format() -> None:
    """Operator tools (write_to_fs) persist named artifacts under the
    same customer-prefixed namespace so ``mc ls blobs/acme/`` shows
    everything for one customer."""
    assert (
        MinioStore.key_session_artifact("acme", "s", "dry_run_summary.md")
        == "blobs/acme/session-artifacts/s/dry_run_summary.md"
    )
    # Leading slash on the relative part is tolerated.
    assert (
        MinioStore.key_session_artifact("acme", "s", "/notes/run1.md") == "blobs/acme/session-artifacts/s/notes/run1.md"
    )


def test_key_trajectory_format() -> None:
    assert MinioStore.key_trajectory("acme", "s", 7) == "blobs/acme/trajectories/s/turn-000007.json"


def test_prefix_trajectories_format() -> None:
    assert MinioStore.prefix_trajectories("acme", "s") == "blobs/acme/trajectories/s/"


def test_customer_prefix_format() -> None:
    """P0: one prefix lists everything for one customer — checkpoints,
    session-artifacts, trajectories, plus the app's extracts/loads/etc."""
    assert MinioStore.customer_prefix("acme") == "blobs/acme/"


# ───────────────────────────── bucket lifecycle ────────────────────────────


@pytest.mark.asyncio
async def test_ensure_bucket_creates_when_missing(mock_minio: tuple[MinioStore, MagicMock]) -> None:
    store, client = mock_minio
    client.bucket_exists.return_value = False
    await store.ensure_bucket()
    client.make_bucket.assert_called_once_with("ludo")


@pytest.mark.asyncio
async def test_ensure_bucket_is_noop_when_present(mock_minio: tuple[MinioStore, MagicMock]) -> None:
    store, client = mock_minio
    client.bucket_exists.return_value = True
    await store.ensure_bucket()
    client.make_bucket.assert_not_called()


# ──────────────────────────────── put / get ────────────────────────────────


@pytest.mark.asyncio
async def test_put_bytes_forwards_length_and_content_type(mock_minio: tuple[MinioStore, MagicMock]) -> None:
    store, client = mock_minio
    await store.put_bytes("k/x.bin", b"hello-world", content_type="application/x-test")
    assert client.put_object.called
    kwargs = client.put_object.call_args.kwargs
    assert kwargs["bucket_name"] == "ludo"
    assert kwargs["object_name"] == "k/x.bin"
    assert kwargs["length"] == len(b"hello-world")
    assert kwargs["content_type"] == "application/x-test"


@pytest.mark.asyncio
async def test_put_json_roundtrips(mock_minio: tuple[MinioStore, MagicMock]) -> None:
    store, client = mock_minio
    await store.put_json("k/j.json", {"a": 1, "b": [1, 2]})
    body = client.put_object.call_args.kwargs["data"].getvalue()
    import json

    assert json.loads(body) == {"a": 1, "b": [1, 2]}
    assert client.put_object.call_args.kwargs["content_type"] == "application/json"


@pytest.mark.asyncio
async def test_put_jsonl_produces_one_row_per_line(mock_minio: tuple[MinioStore, MagicMock]) -> None:
    store, client = mock_minio
    await store.put_jsonl("k/rows.jsonl", [{"id": 1}, {"id": 2}, {"id": 3}])
    body: bytes = client.put_object.call_args.kwargs["data"].getvalue()
    lines = [line for line in body.splitlines() if line]
    assert len(lines) == 3
    assert client.put_object.call_args.kwargs["content_type"] == "application/x-ndjson"


@pytest.mark.asyncio
async def test_put_stream_collects_bytes(mock_minio: tuple[MinioStore, MagicMock]) -> None:
    store, client = mock_minio

    async def gen() -> AsyncIterator[bytes]:
        yield b"hel"
        yield b"lo"
        yield b"!"

    await store.put_stream("k/s.bin", gen())
    assert client.put_object.call_args.kwargs["data"].getvalue() == b"hello!"


@pytest.mark.asyncio
async def test_get_bytes_releases_conn_even_on_success(mock_minio: tuple[MinioStore, MagicMock]) -> None:
    store, client = mock_minio
    response = MagicMock()
    response.read.return_value = b"payload"
    client.get_object.return_value = response

    got = await store.get_bytes("k/x")
    assert got == b"payload"
    response.close.assert_called_once()
    response.release_conn.assert_called_once()


@pytest.mark.asyncio
async def test_get_json_decodes(mock_minio: tuple[MinioStore, MagicMock]) -> None:
    store, client = mock_minio
    response = MagicMock()
    response.read.return_value = b'{"k": 1}'
    client.get_object.return_value = response
    assert await store.get_json("k/x") == {"k": 1}


@pytest.mark.asyncio
async def test_get_stream_yields_chunks_then_closes(mock_minio: tuple[MinioStore, MagicMock]) -> None:
    store, client = mock_minio
    response = MagicMock()
    response.read.side_effect = [b"ab", b"cd", b""]
    client.get_object.return_value = response

    out: list[bytes] = []
    async for chunk in store.get_stream("k/x", chunk_size=2):
        out.append(chunk)

    assert out == [b"ab", b"cd"]
    response.close.assert_called_once()
    response.release_conn.assert_called_once()


# ────────────────────────────────── list / delete ──────────────────────────


@pytest.mark.asyncio
async def test_list_objects_returns_sorted_names(mock_minio: tuple[MinioStore, MagicMock]) -> None:
    store, client = mock_minio

    def _make(name: str) -> MagicMock:
        m = MagicMock()
        m.object_name = name
        return m

    client.list_objects.return_value = [_make("zz"), _make("aa"), _make("mm")]
    result = await store.list_objects("prefix/")
    assert result == ["aa", "mm", "zz"]


@pytest.mark.asyncio
async def test_delete_object_calls_remove(mock_minio: tuple[MinioStore, MagicMock]) -> None:
    store, client = mock_minio
    await store.delete_object("k/x")
    client.remove_object.assert_called_once_with("ludo", "k/x")


@pytest.mark.asyncio
async def test_exists_true_on_stat_success(mock_minio: tuple[MinioStore, MagicMock]) -> None:
    store, client = mock_minio
    client.stat_object.return_value = object()
    assert await store.exists("k/x") is True


@pytest.mark.asyncio
async def test_exists_false_on_nosuchkey(mock_minio: tuple[MinioStore, MagicMock]) -> None:
    from minio.error import S3Error

    store, client = mock_minio
    client.stat_object.side_effect = S3Error(
        code="NoSuchKey",
        message="missing",
        resource="k/x",
        request_id="r",
        host_id="h",
        response=MagicMock(),
    )
    assert await store.exists("k/x") is False


# ──────────────────────────────── presigned ────────────────────────────────


@pytest.mark.asyncio
async def test_presigned_get_inline_default(mock_minio: tuple[MinioStore, MagicMock]) -> None:
    store, client = mock_minio
    client.presigned_get_object.return_value = "https://signed/inline"
    url = await store.presigned_get("blobs/acme/estimates/s/x.html")
    assert url == "https://signed/inline"
    args, kwargs = client.presigned_get_object.call_args
    assert args[0] == "ludo" and args[1] == "blobs/acme/estimates/s/x.html"
    assert kwargs["response_headers"] is None  # inline → renders in browser
    assert kwargs["expires"].days == 7  # SigV4 maximum


@pytest.mark.asyncio
async def test_presigned_get_download_sets_disposition(mock_minio: tuple[MinioStore, MagicMock]) -> None:
    store, client = mock_minio
    client.presigned_get_object.return_value = "https://signed/dl"
    url = await store.presigned_get("k/x.html", download_name="acme_customer.html")
    assert url == "https://signed/dl"
    _args, kwargs = client.presigned_get_object.call_args
    disp = kwargs["response_headers"]["response-content-disposition"]
    assert disp == 'attachment; filename="acme_customer.html"'
