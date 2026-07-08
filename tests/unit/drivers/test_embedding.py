"""Unit tests for the embedding-backed memory layer (Phase A2 #174)."""

from __future__ import annotations

import httpx
import pytest

from agentix.drivers.embedding import (
    CachedEmbeddingDriver,
    EmbeddingCache,
    EmbeddingError,
    HubleEmbeddingDriver,
)
from agentix.storage import SqliteStore
from agentix.storage.vector_index import CosineIndex
from tests.unit.conftest import DeterministicEmbedder as _DeterministicEmbedder

# ──────────────────────── CosineIndex ────────────────────────


def test_cosine_index_empty_returns_empty_topk() -> None:
    idx = CosineIndex()
    assert idx.top_k(query_vec=(0.1, 0.2), k=3) == []


def test_cosine_index_orders_by_similarity() -> None:
    idx = CosineIndex()
    # Three orthogonal-ish vectors in 3D.
    idx.add(key="a", payload={"text": "alpha"}, vector=(1.0, 0.0, 0.0))
    idx.add(key="b", payload={"text": "beta"}, vector=(0.0, 1.0, 0.0))
    idx.add(key="c", payload={"text": "gamma"}, vector=(0.0, 0.0, 1.0))

    # Query closest to "a".
    results = idx.top_k(query_vec=(0.9, 0.1, 0.0), k=2)
    assert len(results) == 2
    assert results[0][1].key == "a"
    assert results[0][0] > results[1][0]


def test_cosine_index_zero_vector_skipped() -> None:
    idx = CosineIndex()
    idx.add(key="zero", payload={}, vector=(0.0, 0.0, 0.0))
    assert len(idx) == 0  # zero-norm vectors rejected


def test_cosine_index_zero_query_returns_empty() -> None:
    idx = CosineIndex()
    idx.add(key="a", payload={}, vector=(1.0, 0.0))
    assert idx.top_k(query_vec=(0.0, 0.0), k=3) == []


# ──────────────────────── EmbeddingCache ─────────────────────


@pytest.mark.asyncio
async def test_embedding_cache_round_trip(sqlite: SqliteStore) -> None:
    cache = EmbeddingCache(sqlite=sqlite)
    await cache.put(model="m1", text="hello world", vector=(0.1, 0.2, 0.3, 0.4))
    got = await cache.get(model="m1", text="hello world")
    assert got is not None
    assert len(got) == 4
    assert all(abs(a - b) < 1e-6 for a, b in zip(got, (0.1, 0.2, 0.3, 0.4), strict=True))


@pytest.mark.asyncio
async def test_embedding_cache_miss_returns_none(sqlite: SqliteStore) -> None:
    cache = EmbeddingCache(sqlite=sqlite)
    assert await cache.get(model="m1", text="never stored") is None


@pytest.mark.asyncio
async def test_embedding_cache_isolates_by_model(sqlite: SqliteStore) -> None:
    """Same text under two models must not collide in the cache."""
    cache = EmbeddingCache(sqlite=sqlite)
    await cache.put(model="m1", text="x", vector=(1.0, 0.0))
    await cache.put(model="m2", text="x", vector=(0.0, 1.0))
    v1 = await cache.get(model="m1", text="x")
    v2 = await cache.get(model="m2", text="x")
    assert v1 is not None and v2 is not None
    assert v1 != v2


# ──────────────────────── CachedEmbeddingDriver ─────────────


@pytest.mark.asyncio
async def test_cached_provider_short_circuits_repeat_calls(sqlite: SqliteStore) -> None:
    """Second embed() call for the same texts hits the cache only — upstream
    receives zero requests on the repeat."""
    upstream = _DeterministicEmbedder()
    cache = EmbeddingCache(sqlite=sqlite)
    cached = CachedEmbeddingDriver(upstream=upstream, cache=cache)

    first = await cached.embed(["alpha", "beta"])
    assert len(first) == 2
    assert len(upstream.calls) == 1
    assert upstream.calls[0] == ["alpha", "beta"]

    # Second call — both cached.
    second = await cached.embed(["alpha", "beta"])
    assert len(second) == 2
    # Upstream NOT called again.
    assert len(upstream.calls) == 1
    # Vectors round-tripped through the cache. Float32 quantization in the
    # SQLite blob means we compare with tolerance, not exact equality.
    for a, b in zip(first, second, strict=True):
        assert len(a.vector) == len(b.vector)
        for x, y in zip(a.vector, b.vector, strict=True):
            assert abs(x - y) < 1e-5


@pytest.mark.asyncio
async def test_cached_provider_partial_cache_only_misses_upstream(sqlite: SqliteStore) -> None:
    """When some texts are cached and some aren't, only the misses go to
    the upstream — and in a single batched call."""
    upstream = _DeterministicEmbedder()
    cache = EmbeddingCache(sqlite=sqlite)
    cached = CachedEmbeddingDriver(upstream=upstream, cache=cache)

    await cached.embed(["alpha"])  # primes cache for alpha
    upstream.calls.clear()

    out = await cached.embed(["alpha", "beta", "gamma"])
    assert len(out) == 3
    # One upstream call, only for the misses.
    assert len(upstream.calls) == 1
    assert sorted(upstream.calls[0]) == sorted(["beta", "gamma"])


# ──────────────────────── HubleEmbeddingDriver ──────────────


def _patch_huble_transport(monkeypatch: pytest.MonkeyPatch, handler):  # type: ignore[no-untyped-def]
    """Replace AsyncClient inside the provider with a MockTransport handler."""
    import agentix.drivers.embedding as embeddings_mod

    real_async_client = httpx.AsyncClient

    def fake_async_client(**kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(**kwargs)

    monkeypatch.setattr(
        embeddings_mod.httpx if hasattr(embeddings_mod, "httpx") else httpx, "AsyncClient", fake_async_client
    )


@pytest.mark.asyncio
async def test_huble_embedding_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    """Happy path: HUBLE returns OpenAI-shape body; we parse N entries."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.read().decode("utf-8")
        return httpx.Response(
            200,
            json={
                "data": [
                    {"embedding": [0.1, 0.2, 0.3]},
                    {"embedding": [0.4, 0.5, 0.6]},
                ]
            },
        )

    _patch_huble_transport(monkeypatch, handler)
    provider = HubleEmbeddingDriver(
        base_url="http://localhost:4000",
        api_key="test-key",
        model="text-embedding-3-small",
    )
    out = await provider.embed(["alpha", "beta"])
    await provider.aclose()

    assert len(out) == 2
    assert out[0].vector == (0.1, 0.2, 0.3)
    assert out[1].vector == (0.4, 0.5, 0.6)
    assert "/api/v2/embeddings" in captured["url"]
    assert '"alpha"' in captured["body"]
    assert '"beta"' in captured["body"]


@pytest.mark.asyncio
async def test_huble_embedding_404_surfaces_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """When HUBLE doesn't expose embeddings, the 404 becomes a clear
    EmbeddingError naming the path — operator knows to either configure
    upstream or fall back to OpenAI."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    _patch_huble_transport(monkeypatch, handler)
    provider = HubleEmbeddingDriver(base_url="http://localhost:4000", api_key="k", model="text-embedding-3-small")
    with pytest.raises(EmbeddingError, match="embeddings endpoint"):
        await provider.embed(["x"])
    await provider.aclose()


@pytest.mark.asyncio
async def test_huble_embedding_malformed_response_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wrong-shape JSON (missing data array, wrong length) raises
    EmbeddingError instead of silently returning bogus vectors."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    _patch_huble_transport(monkeypatch, handler)
    provider = HubleEmbeddingDriver(base_url="http://localhost:4000", api_key="k", model="text-embedding-3-small")
    with pytest.raises(EmbeddingError, match="malformed"):
        await provider.embed(["x"])
    await provider.aclose()


def test_huble_embedding_requires_base_url_and_key() -> None:
    """Construction-time guards — no silent fallback to a global default."""
    with pytest.raises(EmbeddingError, match="base_url"):
        HubleEmbeddingDriver(base_url="", api_key="k", model="m")
    with pytest.raises(EmbeddingError, match="api_key"):
        HubleEmbeddingDriver(base_url="http://x", api_key="", model="m")
