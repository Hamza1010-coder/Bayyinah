"""Corpus backends.

Both implement the same four operations the pipeline needs:

    search(query, k) -> [(Chunk, score)]
    get_article(doc_id, article_no) -> Chunk | None
    idf(term) -> float
    __len__()

``MemoryCorpus`` is for tests and ephemeral use.
``SqliteCorpus`` is the product: persistent, FTS5-backed, no server required.
"""

from __future__ import annotations

import math
from array import array
from pathlib import Path

from ..db import Database
from ..text.chunker import Chunk
from ..text.normalize import content_tokens, normalize_for_match
from .bm25 import BM25
from .embed import HashingEmbedder
from .fusion import rerank, rrf_fuse


class BaseCorpus:
    chunks: list[Chunk]

    def __len__(self) -> int:
        return len(self.chunks)

    def get_article(self, doc_id: str, article_no: str) -> Chunk | None:
        key = str(article_no)
        for chunk in self.chunks:
            if str(chunk.article_no) == key and (not doc_id or chunk.doc_id == doc_id):
                return chunk
        return None

    def idf(self, term: str) -> float:
        raise NotImplementedError


class MemoryCorpus(BaseCorpus):
    def __init__(self, chunks: list[Chunk], embedder: HashingEmbedder | None = None):
        self.chunks = chunks
        self.embedder = embedder or HashingEmbedder()
        self.bm25 = BM25([c.text_norm.split() for c in chunks]) if chunks else None
        self.idf_map = self.bm25.idf if self.bm25 else {}
        self.vectors = self.embedder.embed([c.text_norm for c in chunks]) if chunks else []
        self._by_article: dict[tuple[str, str], int] = {}
        for i, c in enumerate(chunks):
            self._by_article.setdefault((c.doc_id, str(c.article_no)), i)

    def idf(self, term: str) -> float:
        return self.idf_map.get(term, 0.0)

    def get_article(self, doc_id: str, article_no: str) -> Chunk | None:
        idx = self._by_article.get((doc_id, str(article_no)))
        return self.chunks[idx] if idx is not None else None

    def _dense(self, query: str, k: int) -> list[int]:
        qv = self.embedder.embed_one(query)
        scored = [(i, sum(a * b for a, b in zip(qv, v))) for i, v in enumerate(self.vectors)]
        scored.sort(key=lambda t: t[1], reverse=True)
        return [i for i, _ in scored[:k]]

    def _lexical(self, query: str, k: int) -> list[int]:
        if not self.bm25:
            return []
        return [i for i, _ in self.bm25.search(query.split(), top_k=k)]

    def search(self, query: str, k: int = 6, pool: int = 30) -> list[tuple[Chunk, float]]:
        if not self.chunks:
            return []
        fused = rrf_fuse([self._dense(query, pool), self._lexical(query, pool)], weights=[0.4, 1.0])[:pool]
        ranked = rerank(query, fused, self.chunks, self.idf_map)
        return [(self.chunks[i], s) for i, s in ranked[:k]]


class SqliteCorpus(BaseCorpus):
    """Persistent corpus. Lexical via FTS5, dense via stored vectors."""

    def __init__(self, db: Database, embedder: HashingEmbedder | None = None):
        self.db = db
        self.embedder = embedder or HashingEmbedder()
        self._load()

    def _load(self) -> None:
        rows = self.db.chunks()
        self.chunks = []
        self.vectors: list[list[float] | None] = []
        self._index: dict[str, int] = {}
        for row in rows:
            chunk = Chunk(
                chunk_id=row["chunk_id"],
                doc_id=row["doc_id"],
                article_no=row["article_no"],
                chapter=row["chapter"] or "",
                page=int(row["page"] or 0),
                lang=row["lang"] or "ar",
                text_display=row["text_display"],
                text_norm=row["text_norm"],
                url=row["url"] or "",
                synthetic=bool(row["synthetic"]),
            )
            self._index[chunk.chunk_id] = len(self.chunks)
            self.chunks.append(chunk)
            blob = row["vector"]
            if blob:
                vec = array("f")
                vec.frombytes(blob)
                self.vectors.append(vec.tolist())
            else:
                self.vectors.append(None)

        df = self.db.document_frequencies()
        n = max(len(self.chunks), 1)
        self.idf_map = {
            term: math.log(1 + (n - freq + 0.5) / (freq + 0.5)) for term, freq in df.items()
        }
        self._max_idf = math.log(1 + (n + 0.5) / 0.5)

    # -- interface --------------------------------------------------------
    def idf(self, term: str) -> float:
        return self.idf_map.get(term, self._max_idf if self.chunks else 0.0)

    def reload(self) -> None:
        self._load()

    def get_article(self, doc_id: str, article_no: str) -> Chunk | None:
        for chunk in self.chunks:
            if str(chunk.article_no) == str(article_no) and (not doc_id or chunk.doc_id == doc_id):
                return chunk
        return None

    def _dense(self, query: str, pool: int) -> list[int]:
        qv = self.embedder.embed_one(query)
        scored: list[tuple[int, float]] = []
        for i, vec in enumerate(self.vectors):
            if vec is None:
                continue
            scored.append((i, sum(a * b for a, b in zip(qv, vec))))
        scored.sort(key=lambda t: t[1], reverse=True)
        return [i for i, _ in scored[:pool]]

    def _lexical(self, query: str, pool: int) -> list[int]:
        hits = self.db.search_fts(content_tokens(query), limit=pool)
        out = []
        for chunk_id, _score in hits:
            idx = self._index.get(chunk_id)
            if idx is not None:
                out.append(idx)
        return out

    def search(self, query: str, k: int = 6, pool: int = 40) -> list[tuple[Chunk, float]]:
        if not self.chunks:
            return []
        fused = rrf_fuse([self._dense(query, pool), self._lexical(query, pool)], weights=[0.4, 1.0])[:pool]
        ranked = rerank(query, fused, self.chunks, self.idf_map)
        return [(self.chunks[i], s) for i, s in ranked[:k]]

    # -- helpers ----------------------------------------------------------
    def find_quote_source(self, quote: str, candidates: list[Chunk]) -> Chunk | None:
        q = normalize_for_match(quote)
        best, best_score = None, 0.0
        for chunk in candidates:
            src = normalize_for_match(chunk.text_display)
            if q and q in src:
                return chunk
            qt, st = set(q.split()), set(src.split())
            if not qt:
                continue
            score = len(qt & st) / len(qt)
            if score > best_score:
                best, best_score = chunk, score
        return best if best_score > 0.5 else None


def open_corpus(db_path: str | Path) -> SqliteCorpus:
    db = Database(db_path)
    return SqliteCorpus(db)
