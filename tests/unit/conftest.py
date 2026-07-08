"""Shared pytest fixtures for the unit-test suite."""

from __future__ import annotations

import hashlib

from agentix.drivers.embedding import EmbeddingResult


class DeterministicEmbedder:
    """Map each text to a fixed-length vector via SHA-256 → byte-level floats.

    Deterministic + collision-resistant within the test alphabet, no
    network. Vector length 16; values in [0, 1].

    Used by: tests/unit/test_embeddings.py, tests/unit/cli/test_novel_error_report.py
    (and any future tests needing an embedding fake without OpenAI / HUBLE).
    """

    name = "deterministic"
    model = "test-deterministic-v1"

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[EmbeddingResult]:
        self.calls.append(list(texts))
        out: list[EmbeddingResult] = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()[:16]
            vec = tuple(b / 255.0 for b in digest)
            out.append(EmbeddingResult(text=text, vector=vec, model=self.model))
        return out
