"""Unit tests for the MinIO object-store driver — descriptor, error
mapping, seam construction, registry accessor."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from minio.error import S3Error

from agentix.config import DriverSpec
from agentix.drivers import (
    DriverInvalidRequest,
    DriverRateLimited,
    DriverRegistry,
    DriverUnavailable,
    ObjectNotFound,
    ObjectStoreDriver,
)
from agentix.storage.minio_store import MinioConfig


def _config() -> MinioConfig:
    return MinioConfig(endpoint="minio:9000", access_key="k", secret_key="s", bucket="ludo")


def _s3_error(code: str) -> S3Error:
    return S3Error(
        code=code,
        message="boom",
        resource="k/x",
        request_id="r",
        host_id="h",
        response=MagicMock(),
    )


@pytest.fixture
def driver() -> tuple[object, MagicMock]:
    with patch("agentix.drivers.adapters.intrinsic.minio.Minio") as minio_cls:
        from agentix.drivers.adapters.intrinsic.minio import MinioObjectStoreDriver

        client = MagicMock()
        minio_cls.return_value = client
        return MinioObjectStoreDriver(_config()), client


# ───────────────────── descriptor + protocol ─────────────────────


def test_descriptor_is_storage_object(driver: tuple[object, MagicMock]) -> None:
    d, _ = driver
    desc = d.descriptor  # type: ignore[attr-defined]
    assert desc.type == "storage"
    assert desc.modality == "object"
    assert desc.pricing_ref is None  # storage spend is not token-priced


def test_protocol_structural_conformance(driver: tuple[object, MagicMock]) -> None:
    d, _ = driver
    assert isinstance(d, ObjectStoreDriver)


# ───────────────────── error mapping matrix ─────────────────────


@pytest.mark.parametrize(
    ("code", "exc_type"),
    [
        ("NoSuchKey", ObjectNotFound),
        ("NoSuchBucket", ObjectNotFound),
        ("SlowDown", DriverRateLimited),
        ("ServiceUnavailable", DriverUnavailable),
        ("InternalError", DriverUnavailable),
        ("AccessDenied", DriverInvalidRequest),
    ],
)
@pytest.mark.asyncio
async def test_get_bytes_maps_s3_codes(driver: tuple[object, MagicMock], code: str, exc_type: type) -> None:
    d, client = driver
    client.get_object.side_effect = _s3_error(code)
    with pytest.raises(exc_type):
        await d.get_bytes("k/x")  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_connection_error_maps_to_unavailable(driver: tuple[object, MagicMock]) -> None:
    import urllib3.exceptions

    d, client = driver
    client.put_object.side_effect = urllib3.exceptions.MaxRetryError(MagicMock(), "http://minio:9000")
    with pytest.raises(DriverUnavailable):
        await d.put_bytes("k/x", b"data")  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_exists_false_on_not_found_true_otherwise(driver: tuple[object, MagicMock]) -> None:
    d, client = driver
    client.stat_object.side_effect = _s3_error("NoSuchKey")
    assert await d.exists("k/x") is False  # type: ignore[attr-defined]
    client.stat_object.side_effect = None
    client.stat_object.return_value = object()
    assert await d.exists("k/x") is True  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_object_not_found_carries_key(driver: tuple[object, MagicMock]) -> None:
    d, client = driver
    client.get_object.side_effect = _s3_error("NoSuchKey")
    with pytest.raises(ObjectNotFound) as exc_info:
        await d.get_bytes("blobs/acme/x.json")  # type: ignore[attr-defined]
    assert exc_info.value.key == "blobs/acme/x.json"
    assert exc_info.value.retryable is False


# ───────────────────── seam construction ─────────────────────


def test_spec_construction_builds_config_from_options() -> None:
    spec = DriverSpec(
        name="blob-main",
        driver="minio-object-store",
        type="storage",
        modality="object",
        base_url="10.0.99.1:9000",
        options=(("access_key", "ak"), ("bucket", "prod-blobs"), ("secure", "true")),
    )
    with patch("agentix.drivers.adapters.intrinsic.minio.Minio") as minio_cls:
        from agentix.drivers.adapters.intrinsic.minio import MinioObjectStoreDriver

        d = MinioObjectStoreDriver(spec=spec, api_key="sekret")
        assert d.descriptor.name == "blob-main"
        assert d.config.endpoint == "10.0.99.1:9000"
        assert d.config.access_key == "ak"
        assert d.config.secret_key == "sekret"
        assert d.config.bucket == "prod-blobs"
        assert d.config.secure is True
        assert minio_cls.called


def test_construction_without_config_or_spec_raises() -> None:
    from agentix.drivers.adapters.intrinsic.minio import MinioObjectStoreDriver

    with pytest.raises(DriverInvalidRequest):
        MinioObjectStoreDriver()


# ───────────────────── registry accessor ─────────────────────


def test_registry_object_store_accessor(driver: tuple[object, MagicMock]) -> None:
    d, _ = driver
    reg = DriverRegistry()
    reg.register(d)  # type: ignore[arg-type]
    assert reg.object_store() is d
    assert reg.object_store_or_none() is d


def test_registry_object_store_or_none_when_absent() -> None:
    assert DriverRegistry().object_store_or_none() is None


# ───────────────────── store delegation ─────────────────────


@pytest.mark.asyncio
async def test_minio_store_accepts_injected_driver() -> None:
    """MinioStore(driver=...) — the alternate-backend path."""
    from agentix.storage.minio_store import MinioStore

    class _FakeObjectStore:
        def __init__(self) -> None:
            from agentix.drivers import DriverDescriptor

            self.descriptor = DriverDescriptor(name="fake-blob", type="storage", modality="object", source="local")
            self.puts: list[tuple[str, bytes]] = []

        async def aclose(self) -> None: ...

        async def ensure_bucket(self) -> None: ...

        async def put_bytes(self, key: str, data: bytes, *, content_type: str = "") -> None:
            self.puts.append((key, data))

        async def put_file(self, key: str, file_path: str, *, content_type: str = "") -> None: ...

        async def get_bytes(self, key: str) -> bytes:
            return b"{}"

        async def get_stream(self, key: str, *, chunk_size: int = 1):  # pragma: no cover
            yield b""

        async def list_objects(self, prefix: str = "", *, recursive: bool = True) -> list[str]:
            return []

        async def delete_object(self, key: str) -> None: ...

        async def exists(self, key: str) -> bool:
            return False

        async def copy_object(self, source_key: str, dest_key: str) -> None: ...

        async def presigned_get(self, key: str, *, expires=None, download_name=None) -> str:  # type: ignore[no-untyped-def]
            return "https://signed"

    fake = _FakeObjectStore()
    store = MinioStore(driver=fake)  # type: ignore[arg-type]
    await store.put_json("k/x.json", {"a": 1})
    assert fake.puts and fake.puts[0][0] == "k/x.json"
    assert store.driver is fake
