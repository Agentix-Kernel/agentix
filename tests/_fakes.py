"""Shared test fakes — the single canonical home.

One in-memory ``_FakeMinio`` (full ``MinioStore`` protocol) used by both
the unit and integration suites. Previously this class was copy-pasted in
~6 test modules; everything now imports it from here (directly or via the
root ``conftest.py`` ``minio`` fixture).
"""

from __future__ import annotations

import json
import pathlib

from agentix.storage.minio_store import MinioConfig, MinioStore


class _FakeMinio(MinioStore):
    """In-memory ``MinioStore`` for tests — no network, no client."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        super().__init__(MinioConfig(endpoint="localhost:0", access_key="x", secret_key="x"))
        self._client = None  # type: ignore[assignment]

    async def ensure_bucket(self) -> None:
        return None

    async def put_bytes(self, key: str, data: bytes, *, content_type: str = "application/octet-stream") -> None:
        self.objects[key] = data

    async def put_file(self, key: str, file_path: str, *, content_type: str = "application/octet-stream") -> None:
        self.objects[key] = pathlib.Path(file_path).read_bytes()

    async def copy_object(self, source_key: str, dest_key: str) -> None:
        self.objects[dest_key] = self.objects[source_key]

    async def get_bytes(self, key: str) -> bytes:
        if key not in self.objects:
            raise KeyError(key)
        return self.objects[key]

    async def get_json(self, key: str) -> object:
        return json.loads(await self.get_bytes(key))

    async def put_json(self, key: str, payload: object) -> None:
        await self.put_bytes(key, json.dumps(payload).encode("utf-8"))

    async def put_jsonl(self, key: str, rows: object) -> None:
        body = b"\n".join(json.dumps(r).encode("utf-8") for r in rows)  # type: ignore[union-attr]
        await self.put_bytes(key, body, content_type="application/x-ndjson")

    async def list_objects(self, prefix: str = "", *, recursive: bool = True) -> list[str]:
        return sorted(k for k in self.objects if k.startswith(prefix))

    async def delete_object(self, key: str) -> None:
        self.objects.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.objects


__all__ = ["_FakeMinio"]
