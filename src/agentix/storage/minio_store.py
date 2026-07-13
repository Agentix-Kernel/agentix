"""The kernel blob layer — semantics over an object-store driver.

Since v0.5.1 this module is the **semantic** half of the object store:
JSON/JSONL encoding, stream composition and the ``key_*`` prefix
discipline. The raw transport (put/get/list/delete bytes) lives behind
the :class:`agentix.drivers.object_store.ObjectStoreDriver` protocol —
default backend is MinIO (``drivers/adapters/minio.py``); swapping to
S3/Azure/GCS means injecting a different driver, nothing here changes.

The bucket layout is customer-scoped:

    <bucket>/
      blobs/
        <customer>/checkpoints/{session_id}/{checkpoint}.json
        <customer>/session-artifacts/{session_id}/{relative}
        <customer>/trajectories/{session_id}/turn-NNNNNN.json

The ``key_*`` helpers below are the single source of truth for the generic
prefixes — no string concatenation at call sites. App-specific keys (extracts,
loads, reports, …) live in the app under ``BLOB_ROOT``.
"""

from __future__ import annotations

import io
import json
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from agentix.drivers.object_store import ObjectStoreDriver

log = structlog.get_logger(__name__)

# The blob namespace root. Public so app key builders (e.g.
# ``ludo.storage.minio_keys``) share the exact ``blobs/<customer>/…`` scheme.
BLOB_ROOT = "blobs"
_BLOB_ROOT = BLOB_ROOT


@dataclass(frozen=True)
class MinioConfig:
    """Connection configuration for a MinIO (or S3) endpoint."""

    endpoint: str
    access_key: str
    secret_key: str
    bucket: str = "agentix"
    secure: bool = False
    region: str | None = None


class MinioStore:
    """The kernel blob layer, composed over an :class:`ObjectStoreDriver`.

    ``MinioStore(config)`` keeps working exactly as before (builds the
    MinIO driver internally); ``MinioStore(driver=...)`` injects an
    alternate backend. A single instance can be shared across sessions —
    thread-safety is the driver's contract.
    """

    def __init__(
        self,
        config: MinioConfig | None = None,
        *,
        driver: ObjectStoreDriver | None = None,
    ) -> None:
        if driver is None:
            if config is None:
                raise TypeError("MinioStore needs a MinioConfig or an ObjectStoreDriver")
            # Lazy import: storage must stay importable without pulling the
            # adapter (and the drivers package) unless actually constructed
            # from config.
            from agentix.drivers.adapters.intrinsic.minio import MinioObjectStoreDriver

            driver = MinioObjectStoreDriver(config)
        self.config = config
        self._driver = driver

    @property
    def driver(self) -> ObjectStoreDriver:
        """The transport underneath — exposed for registry/lifecycle wiring."""
        return self._driver

    # ──────────────────────────── bucket lifecycle ─────────────────────────

    async def ensure_bucket(self) -> None:
        """Create the configured bucket if it does not already exist."""
        await self._driver.ensure_bucket()

    # ──────────────────────────────── put ──────────────────────────────────

    async def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> None:
        """Upload raw bytes under ``key``."""
        await self._driver.put_bytes(key, data, content_type=content_type)

    async def put_json(self, key: str, payload: Any) -> None:
        """Upload ``payload`` as canonical JSON under ``key``.

        Uses ``default=str`` so date / datetime / Decimal / UUID values
        from Pydantic ``model_dump()`` (which returns native Python
        objects) serialise cleanly. Schema metadata carries date
        fields; without ``default=str`` a payload containing one raises
        ``TypeError: Object of type date is not JSON serializable``,
        and the agent cannot recover from a tool that always raises —
        defensive serialisation in the storage layer is the right fix.
        """
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        await self.put_bytes(key, body, content_type="application/json")

    async def put_jsonl(self, key: str, rows: Iterable[Any]) -> None:
        """Upload an iterable of rows as newline-delimited JSON under ``key``.

        Materialises the iterable in memory before uploading — the caller
        should chunk extracts into session/model boundaries before calling
        this. Use ``put_stream`` for outputs larger than a few hundred MB.

        Uses ``default=str`` for the same reason as ``put_json``: source
        record extracts include date / datetime fields that Pydantic
        leaves as native Python objects.
        """
        buffer = io.BytesIO()
        for row in rows:
            buffer.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=str,
                ).encode("utf-8")
            )
            buffer.write(b"\n")
        body = buffer.getvalue()
        await self.put_bytes(key, body, content_type="application/x-ndjson")

    async def put_stream(
        self,
        key: str,
        source: AsyncIterator[bytes],
        *,
        content_type: str = "application/octet-stream",
    ) -> None:
        """Upload an async byte stream under ``key``.

        Accumulates the stream into memory before the transport put, which
        requires a sized source. This is the simplest correct approach;
        for very large payloads, prefer ``put_file`` (multipart).
        """
        chunks: list[bytes] = []
        async for chunk in source:
            chunks.append(chunk)
        body = b"".join(chunks)
        await self.put_bytes(key, body, content_type=content_type)

    async def put_file(
        self,
        key: str,
        file_path: str,
        *,
        content_type: str = "application/octet-stream",
    ) -> None:
        """Upload a local file under ``key`` via multipart — disk-bounded, not RAM-bounded.

        Use for extracts of arbitrary size: writer streams pages to a temp
        file, then the transport chunks it server-side. No in-memory
        accumulation.
        """
        await self._driver.put_file(key, file_path, content_type=content_type)

    async def copy_object(self, source_key: str, dest_key: str) -> None:
        """Server-side copy within the bucket — no client-side transfer.

        Used by the extract cache (G20): a cache hit copies the prior
        session's blob to the current session's expected key so every
        downstream session-scoped reader (load_to_odoo, verify_migration)
        finds it without knowing about the cache.
        """
        await self._driver.copy_object(source_key, dest_key)

    async def presigned_get(
        self,
        key: str,
        *,
        expires: timedelta = timedelta(days=7),
        download_name: str | None = None,
    ) -> str:
        """Presigned GET URL for ``key`` — a signed, time-limited link that
        needs no credentials (object stays private). ``expires`` caps at 7 days
        (the SigV4 maximum). ``download_name`` adds a content-disposition so the
        link forces a download with that filename instead of inline rendering.
        """
        return await self._driver.presigned_get(key, expires=expires, download_name=download_name)

    # ──────────────────────────────── get ──────────────────────────────────

    async def get_bytes(self, key: str) -> bytes:
        """Download the object at ``key`` as raw bytes."""
        return await self._driver.get_bytes(key)

    async def get_json(self, key: str) -> Any:
        """Download and JSON-decode the object at ``key``."""
        body = await self.get_bytes(key)
        return json.loads(body)

    async def get_stream(
        self,
        key: str,
        *,
        chunk_size: int = 64 * 1024,
    ) -> AsyncIterator[bytes]:
        """Yield the object at ``key`` in ``chunk_size`` byte slices."""
        async for chunk in self._driver.get_stream(key, chunk_size=chunk_size):
            yield chunk

    # ──────────────────────────────── list ─────────────────────────────────

    async def list_objects(
        self,
        prefix: str = "",
        *,
        recursive: bool = True,
    ) -> list[str]:
        """Return object keys under ``prefix``, lexicographically sorted."""
        return await self._driver.list_objects(prefix, recursive=recursive)

    # ─────────────────────────────── delete ────────────────────────────────

    async def delete_object(self, key: str) -> None:
        await self._driver.delete_object(key)

    async def exists(self, key: str) -> bool:
        return await self._driver.exists(key)

    # ─────────────────────────── well-known keys ───────────────────────────
    #
    # Every session-scoped key lives under ``blobs/<customer>/…`` so operators
    # can list, GC, or archive per-customer from the bucket alone without
    # cross-referencing SQLite. These are the **generic** (app-agnostic) keys;
    # app-specific keys (extracts, loads, reports, estimates, snapshots) live in
    # the app, e.g. ``ludo.storage.minio_keys``. Path shape:
    #
    #   blobs/<customer>/checkpoints/<session_id>/<checkpoint>.json
    #   blobs/<customer>/session-artifacts/<session_id>/<relative>
    #   blobs/<customer>/trajectories/<session_id>/turn-NNNNNN.json
    #
    # ``_probe/`` is kept at root (not session-scoped, not customer-scoped)
    # for operator health pings.
    #
    # ``BLOB_ROOT`` is exported so app key builders share the same namespace.

    @staticmethod
    def customer_prefix(customer: str) -> str:
        """Return ``blobs/<customer>/`` — the listing root for one account."""
        return f"{_BLOB_ROOT}/{customer}/"

    @staticmethod
    def key_checkpoint(customer: str, session_id: str, checkpoint: str) -> str:
        """Key for a named checkpoint blob within ``session_id``."""
        return f"{_BLOB_ROOT}/{customer}/checkpoints/{session_id}/{checkpoint}.json"

    @staticmethod
    def key_session_artifact(customer: str, session_id: str, relative: str) -> str:
        """Key for the agent's ``write_to_fs`` outputs under one session."""
        return f"{_BLOB_ROOT}/{customer}/session-artifacts/{session_id}/{relative.lstrip('/')}"

    @staticmethod
    def key_trajectory(customer: str, session_id: str, turn_index: int) -> str:
        """Key for one turn's trajectory snapshot (TrajectoryCaptureMiddleware)."""
        return f"{_BLOB_ROOT}/{customer}/trajectories/{session_id}/turn-{turn_index:06d}.json"

    @staticmethod
    def prefix_trajectories(customer: str, session_id: str) -> str:
        """Prefix for listing every turn snapshot in a session."""
        return f"{_BLOB_ROOT}/{customer}/trajectories/{session_id}/"
