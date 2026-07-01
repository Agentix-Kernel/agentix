"""Async wrapper around MinIO (S3-compatible) — the kernel blob layer.

MinIO's first-party Python SDK is synchronous; we run every call in a
worker thread via ``asyncio.to_thread`` so the event loop stays unblocked.
This is acceptable for the blob workload — MinIO calls happen at
checkpoint boundaries, not per-turn.

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

import asyncio
import io
import json
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import structlog
from minio import Minio
from minio.error import S3Error

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
    bucket: str = "ludo"
    secure: bool = False
    region: str | None = None


class MinioStore:
    """Async MinIO client for LUDO's blob layer.

    Thread-safe at the Python level: every public method offloads to a
    worker via ``asyncio.to_thread``. A single ``MinioStore`` instance can
    be shared across sessions.
    """

    def __init__(self, config: MinioConfig) -> None:
        self.config = config
        self._client = Minio(
            endpoint=config.endpoint,
            access_key=config.access_key,
            secret_key=config.secret_key,
            secure=config.secure,
            region=config.region,
        )

    # ──────────────────────────── bucket lifecycle ─────────────────────────

    async def ensure_bucket(self) -> None:
        """Create the configured bucket if it does not already exist."""

        def _ensure() -> None:
            if not self._client.bucket_exists(self.config.bucket):
                self._client.make_bucket(self.config.bucket)

        await asyncio.to_thread(_ensure)
        log.debug("minio.bucket_ready", bucket=self.config.bucket)

    # ──────────────────────────────── put ──────────────────────────────────

    async def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> None:
        """Upload raw bytes under ``key``."""

        def _put() -> None:
            self._client.put_object(
                bucket_name=self.config.bucket,
                object_name=key,
                data=io.BytesIO(data),
                length=len(data),
                content_type=content_type,
            )

        await asyncio.to_thread(_put)
        log.debug("minio.put", key=key, bytes=len(data))

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

        Accumulates the stream into memory before invoking minio-py, which
        requires a sync seekable source. This is the simplest correct
        approach; for very large payloads, prefer multi-part uploads.
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
        file, then this routine hands the path to minio-py's fput_object,
        which chunks it server-side. No in-memory accumulation.
        """

        def _put() -> None:
            self._client.fput_object(
                bucket_name=self.config.bucket,
                object_name=key,
                file_path=file_path,
                content_type=content_type,
            )

        await asyncio.to_thread(_put)
        log.debug("minio.put_file", key=key, path=file_path)

    async def copy_object(self, source_key: str, dest_key: str) -> None:
        """Server-side copy within the bucket — no client-side transfer.

        Used by the extract cache (G20): a cache hit copies the prior
        session's blob to the current session's expected key so every
        downstream session-scoped reader (load_to_odoo, verify_migration)
        finds it without knowing about the cache.
        """
        from minio.commonconfig import CopySource

        def _copy() -> None:
            self._client.copy_object(
                bucket_name=self.config.bucket,
                object_name=dest_key,
                source=CopySource(self.config.bucket, source_key),
            )

        await asyncio.to_thread(_copy)
        log.debug("minio.copy", source=source_key, dest=dest_key)

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
        response_headers: dict[str, str | list[str] | tuple[str]] | None = (
            {"response-content-disposition": f'attachment; filename="{download_name}"'} if download_name else None
        )
        return await asyncio.to_thread(
            self._client.presigned_get_object,
            self.config.bucket,
            key,
            expires=expires,
            response_headers=response_headers,
        )

    # ──────────────────────────────── get ──────────────────────────────────

    async def get_bytes(self, key: str) -> bytes:
        """Download the object at ``key`` as raw bytes."""

        def _get() -> bytes:
            response = self._client.get_object(self.config.bucket, key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()

        return await asyncio.to_thread(_get)

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
        """Yield the object at ``key`` in ``chunk_size`` byte slices.

        The underlying minio-py read is sync; chunks are pumped through
        ``asyncio.to_thread`` one at a time so a slow consumer doesn't
        block the event loop.
        """
        # Returned object is a HTTPResponse-like; we can't keep it open across
        # threads cleanly, so we materialise lazily chunk-by-chunk.
        response = await asyncio.to_thread(self._client.get_object, self.config.bucket, key)
        try:
            while True:
                chunk = await asyncio.to_thread(response.read, chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            await asyncio.to_thread(response.close)
            await asyncio.to_thread(response.release_conn)

    # ──────────────────────────────── list ─────────────────────────────────

    async def list_objects(
        self,
        prefix: str = "",
        *,
        recursive: bool = True,
    ) -> list[str]:
        """Return object keys under ``prefix``, lexicographically sorted."""

        def _list() -> list[str]:
            return [
                obj.object_name
                for obj in self._client.list_objects(
                    bucket_name=self.config.bucket,
                    prefix=prefix,
                    recursive=recursive,
                )
                if obj.object_name
            ]

        keys = await asyncio.to_thread(_list)
        return sorted(keys)

    # ─────────────────────────────── delete ────────────────────────────────

    async def delete_object(self, key: str) -> None:
        await asyncio.to_thread(self._client.remove_object, self.config.bucket, key)
        log.debug("minio.delete", key=key)

    async def exists(self, key: str) -> bool:
        def _stat() -> bool:
            try:
                self._client.stat_object(self.config.bucket, key)
            except S3Error as e:
                if e.code in ("NoSuchKey", "NoSuchBucket"):
                    return False
                raise
            return True

        return await asyncio.to_thread(_stat)

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
