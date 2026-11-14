"""Pure-Python BM25. Small corpora, no Elasticsearch, no dependencies.

Deliberately boring: a legal corpus is ~500k tokens and fits in memory many
times over. Adding a search cluster here would be resume-driven engineering.
"""

from __future__ import annotations

import math
from collections import Counter


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.docs = docs
        self.k1 = k1
        self.b = b
        self.n = len(docs)
        self.doc_len = [len(d) for d in docs]
        self.avg_len = (sum(self.doc_len) / self.n) if self.n else 0.0
        self.tf = [Counter(d) for d in docs]
        df: Counter[str] = Counter()
        for c in self.tf:
            df.update(c.keys())
        self.idf = {
            term: math.log(1 + (self.n - freq + 0.5) / (freq + 0.5))
            for term, freq in df.items()
        }

    def search(self, query_tokens: list[str], top_k: int = 20) -> list[tuple[int, float]]:
        scores: list[tuple[int, float]] = []
        for i, tf in enumerate(self.tf):
            score = 0.0
            norm = self.k1 * (1 - self.b + self.b * (self.doc_len[i] / (self.avg_len or 1)))
            for term in query_tokens:
                freq = tf.get(term)
                if not freq:
                    continue
                score += self.idf.get(term, 0.0) * (freq * (self.k1 + 1)) / (freq + norm)
            if score > 0:
                scores.append((i, score))
        scores.sort(key=lambda t: t[1], reverse=True)
        return scores[:top_k]
