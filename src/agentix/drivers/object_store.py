"""Object-store driver family — the storage-type object transport.

The first non-model driver type. The split with ``storage/minio_store.py``
is deliberate: the **store** (``MinioStore``) is the kernel's semantic
layer — JSON/JSONL encoding, streaming composition, the ``key_*`` prefix
discipline — while the **driver** is the raw transport underneath
(put/get/list/delete bytes against an S3-compatible or other backend).
Swapping the physical backend (S3, Azure Blob, GCS) means writing a new
driver; the store and every consumer stay untouched.

Verbs are transport primitives only. Anything expressible as composition
over these verbs (``put_json``, ``put_stream`` accumulation) belongs to
the store, not the protocol.

Canonical doc: ``docs/drivers.md``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Protocol, runtime_checkable

from agentix.drivers.base import Driver, DriverError

__all__ = ["ObjectNotFound", "ObjectStoreDriver"]


class ObjectNotFound(DriverError):
    """The requested object (or bucket) does not exist. Not retryable."""

    def __init__(self, message: str, *, driver: str, key: str | None = None) -> None:
        super().__init__(message, driver=driver, retryable=False)
        self.key = key


@runtime_checkable
class ObjectStoreDriver(Driver, Protocol):
    """Protocol every object-store adapter implements — storage-type,
    ``modality="object"``.

    Error contract: adapters classify once into the driver taxonomy —
    missing object → :class:`ObjectNotFound`; backend throttling →
    ``DriverRateLimited``; connectivity/5xx → ``DriverUnavailable``;
    everything else → ``DriverInvalidRequest``.
    """

    async def ensure_bucket(self) -> None:
        """Create the configured bucket/container if it does not exist."""
        ...

    async def put_bytes(self, key: str, data: bytes, *, content_type: str = "application/octet-stream") -> None: ...

    async def put_file(self, key: str, file_path: str, *, content_type: str = "application/octet-stream") -> None:
        """Upload a local file — disk-bounded (multipart), not RAM-bounded."""
        ...

    async def get_bytes(self, key: str) -> bytes: ...

    def get_stream(self, key: str, *, chunk_size: int = 64 * 1024) -> AsyncIterator[bytes]:
        """Yield the object in ``chunk_size`` byte slices."""
        ...

    async def list_objects(self, prefix: str = "", *, recursive: bool = True) -> list[str]:
        """Object keys under ``prefix``, lexicographically sorted."""
        ...

    async def delete_object(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...

    async def copy_object(self, source_key: str, dest_key: str) -> None:
        """Server-side copy within the bucket — no client-side transfer."""
        ...

    async def presigned_get(
        self,
        key: str,
        *,
        expires: timedelta = timedelta(days=7),
        download_name: str | None = None,
    ) -> str:
        """Signed, time-limited GET URL; the object stays private."""
        ...
