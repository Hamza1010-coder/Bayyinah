"""Reranking and fusion, shared by every corpus backend."""

from __future__ import annotations

from ..text.normalize import content_tokens

RRF_K = 60


def rrf_fuse(rankings: list[list[int]], k: int = RRF_K, weights: list[float] | None = None) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion. Weights let a weak retriever contribute less."""
    weights = weights or [1.0] * len(rankings)
    scores: dict[int, float] = {}
    for ranking, weight in zip(rankings, weights):
        for rank, idx in enumerate(ranking):
            scores[idx] = scores.get(idx, 0.0) + weight / (k + rank + 1)
    return sorted(scores.items(), key=lambda t: t[1], reverse=True)


def rerank(
    query: str,
    candidates: list[tuple[int, float]],
    chunks: list,
    idf: dict[str, float],
) -> list[tuple[int, float]]:
    """IDF-weighted overlap + bigram phrase bonus.

    Stands in for a cross-encoder. A query term appearing in every article
    ("عامل", "خدمة") must not outvote a term appearing in one ("استقال").
    Bigrams separate "مكافأة نهاية الخدمة" from "مدة الخدمة", which share a word
    but are different legal concepts.
    """
    q_tokens = content_tokens(query)
    q_terms = set(q_tokens)
    if not q_terms:
        return candidates
    q_bigrams = set(zip(q_tokens, q_tokens[1:]))
    total_idf = sum(idf.get(t, 1.0) for t in q_terms) or 1.0

    out: list[tuple[int, float]] = []
    for idx, base in candidates:
        c_tokens = content_tokens(chunks[idx].text_norm)
        c_terms = set(c_tokens)
        matched = q_terms & c_terms
        weighted = sum(idf.get(t, 1.0) for t in matched) / total_idf
        phrase = 0.0
        if q_bigrams:
            c_bigrams = set(zip(c_tokens, c_tokens[1:]))
            phrase = len(q_bigrams & c_bigrams) / len(q_bigrams)
        out.append((idx, base + weighted + 0.75 * phrase))
    return sorted(out, key=lambda t: t[1], reverse=True)
