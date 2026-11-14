"""Embedding backends.

``HashingEmbedder`` is a real (if weak) dense retriever: feature hashing over
character n-grams plus word unigrams, L2-normalized. It exists so the hybrid
pipeline is exercisable end-to-end on a CPU with no model download, and so
tests are deterministic.

``BgeM3Embedder`` is the production path and is intentionally a thin adapter --
swap the model, keep the interface.
"""

from __future__ import annotations

import hashlib
import math
from typing import Protocol, Sequence

from ..text.normalize import char_ngrams, tokenize

DIM = 512


class Embedder(Protocol):
    dim: int
    name: str

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def _l2(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]


class HashingEmbedder:
    """Deterministic, dependency-free. Signed feature hashing."""

    name = "hashing-ngram-v1"
    dim = DIM

    def __init__(self, dim: int = DIM, n: int = 3):
        self.dim = dim
        self.n = n

    def _features(self, text: str) -> list[tuple[str, float]]:
        feats: list[tuple[str, float]] = [(f"w:{t}", 1.0) for t in tokenize(text)]
        for g in char_ngrams(text, self.n):
            feats.append((f"c:{g}", 0.5))
        return feats

    def embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for feat, weight in self._features(text):
            h = hashlib.blake2b(feat.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(h[:4], "big") % self.dim
            sign = 1.0 if h[4] & 1 else -1.0
            vec[idx] += sign * weight
        return _l2(vec)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed_one(t) for t in texts]


class BgeM3Embedder:  # pragma: no cover - requires torch + model weights
    """Production embedder. Requires ``pip install -e .[ml]``."""

    name = "bge-m3"
    dim = 1024

    def __init__(self, model_name: str = "BAAI/bge-m3"):
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "BGE-M3 backend requires the [ml] extra: pip install -e '.[ml]'\n"
                "The rest of the system runs without it using HashingEmbedder."
            ) from exc
        self.model = SentenceTransformer(model_name)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:  # pragma: no cover
        return [list(map(float, v)) for v in self.model.encode(list(texts), normalize_embeddings=True)]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))
