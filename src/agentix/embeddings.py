"""Embedding-backed semantic recall — Hermes-shape memory layer.

The deterministic catalogue (``error_catalogue.yaml``) plus the
hand-curated memory gives LUDO high-signal symbolic recall via exact
patterns. The agent loop also needs *fuzzy* recall — given a novel
error message, which catalogue patterns are most semantically similar?
Today this lives as Jaccard token-overlap in
``cli.novel_error_report._nearest_catalogue_patterns``. Jaccard catches
shared vocabulary but misses paraphrases ("invalid foreign key" vs
"missing external id").

This module replaces the Jaccard path (when an embedding provider is
configured) with cosine similarity over real embeddings. The provider
is pluggable so vendor-neutrality survives:

*:class:`OpenAIEmbeddingProvider` — uses the openai SDK we already ship
  for the chat path. ``text-embedding-3-small`` is $0.02 / 1M tokens,
  cheap enough that the entire catalogue costs cents to embed once.
* Future: HubleEmbeddingProvider, GroqEmbeddingProvider, local FAISS
  with sentence-transformers.

The in-memory index is pure-Python cosine similarity — fine for the
catalogue's ~50 patterns. When the memory grows past ~10K pages, swap to
FAISS without changing the public interface.

Caching: every embed() call goes through a SQLite cache keyed by
``sha256(text + model)`` so re-runs don't re-pay the embedding cost.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

import structlog

log = structlog.get_logger(__name__)


class EmbeddingError(RuntimeError):
    """Raised when an EmbeddingProvider fails or is misconfigured."""


@dataclass(frozen=True)
class EmbeddingResult:
    """Per-text embedding output — vector + the model that produced it."""

    text: str
    vector: tuple[float, ...]
    model: str

    @property
    def dim(self) -> int:
        return len(self.vector)


class EmbeddingProvider(Protocol):
    """Protocol for embedding backends.

    Implementations must be safe to call from an async context. Vector
    length must be stable across calls of the same instance (otherwise
    the cosine index breaks).
    """

    name: str
    model: str

    async def embed(self, texts: list[str]) -> list[EmbeddingResult]: ...


# ──────────────────────── OpenAI backend ──────────────────────────────


class OpenAIEmbeddingProvider:
    """OpenAI text-embedding-3-small (or any compatible model).

    Re-uses the ``openai`` SDK we ship for chat. Honors ``OPENAI_API_KEY``
    or an explicit ``api_key`` arg. Default model is ``text-embedding-3-small``
    (1536 dims) — cheap, fast, and good enough for catalogue + memory recall.
    """

    name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "text-embedding-3-small",
        base_url: str | None = None,
    ) -> None:
        from openai import AsyncOpenAI  # local import — keep startup fast

        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise EmbeddingError("OpenAIEmbeddingProvider: OPENAI_API_KEY not set and no api_key passed")
        self.model = model
        self._client = AsyncOpenAI(api_key=key, base_url=base_url)

    async def embed(self, texts: list[str]) -> list[EmbeddingResult]:
        if not texts:
            return []
        try:
            resp = await self._client.embeddings.create(model=self.model, input=texts)
        except Exception as exc:
            raise EmbeddingError(f"OpenAI embedding failed: {exc}") from exc
        out: list[EmbeddingResult] = []
        for src, datum in zip(texts, resp.data, strict=True):
            out.append(EmbeddingResult(text=src, vector=tuple(datum.embedding), model=self.model))
        return out


# ──────────────────────── HUBLE backend ───────────────────────────────


class HubleEmbeddingProvider:
    """HUBLE gateway embedding endpoint.

    POSTs to ``{base_url}{embeddings_path}`` with the OpenAI-shape body
    ``{model, input}`` and parses the OpenAI-shape response
    ``{data: [{embedding: [...]},...]}``. HUBLE proxies to whichever
    upstream embedding model is configured (text-embedding-3-small,
    voyage-3, cohere-embed-v3, …) — vendor-neutral by design.

    Configured via ``providers.huble`` in ludo.yaml plus an
    ``embedding_model`` field. Default ``text-embedding-3-small`` (cheap,
    fast, 1536 dims) which most HUBLE deployments support.
    """

    name = "huble"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str = "text-embedding-3-small",
        embeddings_path: str = "/api/v2/embeddings",
        timeout_seconds: float = 60.0,
    ) -> None:
        import httpx  # local import — keep import-time cheap

        if not base_url:
            raise EmbeddingError("HubleEmbeddingProvider: base_url required")
        if not api_key:
            raise EmbeddingError("HubleEmbeddingProvider: api_key required")
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._path = embeddings_path
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "X-API-Key": api_key,
                "Content-Type": "application/json",
            },
            timeout=timeout_seconds,
        )

    async def embed(self, texts: list[str]) -> list[EmbeddingResult]:
        if not texts:
            return []
        import httpx

        try:
            response = await self._client.post(
                self._path,
                json={"model": self.model, "input": texts},
            )
        except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException) as exc:
            raise EmbeddingError(f"HUBLE embedding unreachable: {exc}") from exc
        if response.status_code == 404:
            raise EmbeddingError(
                f"HUBLE deployment doesn't expose {self._path} — "
                f"embeddings endpoint not configured upstream. "
                f"Set providers.huble.embeddings_path or fall back to OpenAIEmbeddingProvider."
            )
        if response.status_code >= 400:
            raise EmbeddingError(f"HUBLE embedding HTTP {response.status_code}: {response.text[:200]}")
        try:
            body = response.json()
        except ValueError as exc:
            raise EmbeddingError(f"HUBLE embedding non-JSON response: {response.text[:200]}") from exc
        data = body.get("data")
        if not isinstance(data, list) or len(data) != len(texts):
            raise EmbeddingError(
                f"HUBLE embedding malformed response: expected {len(texts)} entries, got "
                f"{len(data) if isinstance(data, list) else type(data).__name__}"
            )
        out: list[EmbeddingResult] = []
        for src, entry in zip(texts, data, strict=True):
            vec = entry.get("embedding") if isinstance(entry, dict) else None
            if not isinstance(vec, list):
                raise EmbeddingError(f"HUBLE embedding entry missing 'embedding' list: {entry}")
            out.append(EmbeddingResult(text=src, vector=tuple(float(v) for v in vec), model=self.model))
        return out

    async def aclose(self) -> None:
        await self._client.aclose()


# ──────────────────────── In-memory cosine index ───────────────────────


@dataclass
class _IndexEntry:
    key: str
    payload: dict[str, Any]
    vector: tuple[float, ...]
    norm: float


@dataclass
class CosineIndex:
    """Pure-Python cosine-similarity index.

    Add entries with:meth:`add`, query with:meth:`top_k`. The vectors
    are kept verbatim (no PCA / quantisation) — small catalogues only.
    For 10k+ entries swap the implementation to FAISS or hnswlib;
    interface is stable.
    """

    entries: list[_IndexEntry] = field(default_factory=list)

    def add(self, *, key: str, payload: dict[str, Any], vector: tuple[float, ...]) -> None:
        norm = _l2_norm(vector)
        if norm == 0.0:
            log.warning("embeddings.zero_vector", key=key)
            return
        self.entries.append(_IndexEntry(key=key, payload=payload, vector=vector, norm=norm))

    def top_k(self, query_vec: tuple[float, ...], k: int = 3) -> list[tuple[float, _IndexEntry]]:
        """Return the top-``k`` entries by cosine similarity, descending."""
        if not self.entries:
            return []
        q_norm = _l2_norm(query_vec)
        if q_norm == 0.0:
            return []
        scored: list[tuple[float, _IndexEntry]] = []
        for entry in self.entries:
            score = _dot(query_vec, entry.vector) / (q_norm * entry.norm)
            scored.append((score, entry))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored[:k]

    def __len__(self) -> int:
        return len(self.entries)


def _dot(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _l2_norm(v: tuple[float, ...]) -> float:
    return math.sqrt(sum(x * x for x in v))


# ──────────────────────── SQLite-backed cache ─────────────────────────


class EmbeddingCache:
    """Disk-backed cache so repeated runs don't re-embed identical texts.

    Keyed by ``sha256(model || text)`` — model in the key so swapping
    providers doesn't return stale vectors. Stores vectors as a packed
    little-endian float32 blob to keep size down (~6KB per 1536-dim vec).

    Uses the existing SqliteStore connection pool so we don't add a new
    db file. Async-safe: SQLite handles per-row locking.
    """

    def __init__(self, sqlite: object) -> None:
        # Late-bound to avoid the agentix.storage import at module level
        # (this module is imported by both tools and storage).
        from agentix.storage import SqliteStore

        if not isinstance(sqlite, SqliteStore):
            raise TypeError(f"EmbeddingCache needs a SqliteStore, got {type(sqlite).__name__}")
        self._sqlite = sqlite
        self._table_ready = False

    async def ensure_table(self) -> None:
        if self._table_ready:
            return
        db = self._sqlite._conn()
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS embedding_cache (
                key TEXT PRIMARY KEY,
                model TEXT NOT NULL,
                dim INTEGER NOT NULL,
                vector BLOB NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.commit()
        self._table_ready = True

    async def get(self, *, model: str, text: str) -> tuple[float, ...] | None:
        await self.ensure_table()
        key = _cache_key(model, text)
        db = self._sqlite._conn()
        cursor = await db.execute(
            "SELECT vector FROM embedding_cache WHERE key = ?",
            (key,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return _unpack_vector(row[0])

    async def put(self, *, model: str, text: str, vector: tuple[float, ...]) -> None:
        await self.ensure_table()
        key = _cache_key(model, text)
        blob = _pack_vector(vector)
        db = self._sqlite._conn()
        await db.execute(
            "INSERT OR REPLACE INTO embedding_cache(key, model, dim, vector) VALUES (?, ?, ?, ?)",
            (key, model, len(vector), blob),
        )
        await db.commit()


def _cache_key(model: str, text: str) -> str:
    h = hashlib.sha256()
    h.update(model.encode("utf-8"))
    h.update(b"\0")
    h.update(text.encode("utf-8"))
    return h.hexdigest()


def _pack_vector(vec: tuple[float, ...]) -> bytes:
    import struct

    return struct.pack(f"<{len(vec)}f", *vec)


def _unpack_vector(blob: bytes) -> tuple[float, ...]:
    import struct

    n = len(blob) // 4
    return tuple(struct.unpack(f"<{n}f", blob))


# ──────────────────────── Cached provider wrapper ─────────────────────


class CachedEmbeddingProvider:
    """Wrap any EmbeddingProvider in the SQLite cache so identical texts
    only hit the upstream once.

    Cache hits short-circuit before the upstream call — zero token spend
    on repeat queries.
    """

    name = "cached"

    def __init__(self, *, upstream: EmbeddingProvider, cache: EmbeddingCache) -> None:
        self._upstream = upstream
        self._cache = cache
        self.model = upstream.model

    async def embed(self, texts: list[str]) -> list[EmbeddingResult]:
        if not texts:
            return []
        # Fan out cache lookups in parallel.
        cached_vecs = await asyncio.gather(*(self._cache.get(model=self.model, text=t) for t in texts))
        misses_idx = [i for i, v in enumerate(cached_vecs) if v is None]
        results: list[EmbeddingResult] = [
            EmbeddingResult(text=texts[i], vector=cached_vecs[i] or (), model=self.model)
            if cached_vecs[i] is not None
            else EmbeddingResult(text=texts[i], vector=(), model=self.model)
            for i in range(len(texts))
        ]
        if not misses_idx:
            return results
        # One batch upstream call for all cache misses.
        miss_texts = [texts[i] for i in misses_idx]
        upstream_results = await self._upstream.embed(miss_texts)
        for idx, ur in zip(misses_idx, upstream_results, strict=True):
            results[idx] = ur
        # Persist new vectors back to cache.
        await asyncio.gather(
            *(self._cache.put(model=self.model, text=ur.text, vector=ur.vector) for ur in upstream_results)
        )
        log.info(
            "embeddings.batch",
            cache_hits=len(texts) - len(misses_idx),
            cache_misses=len(misses_idx),
            model=self.model,
        )
        return results


__all__ = [
    "CachedEmbeddingProvider",
    "CosineIndex",
    "EmbeddingCache",
    "EmbeddingError",
    "EmbeddingProvider",
    "EmbeddingResult",
    "HubleEmbeddingProvider",
    "OpenAIEmbeddingProvider",
]
