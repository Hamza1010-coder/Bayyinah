"""Backwards-compatible in-memory store used by tests and scripts.

The product path is :class:`bayyinah.retrieval.corpus.SqliteCorpus`. This shim
keeps the older `InMemoryStore` name working and loads a JSONL chunk dump, which
is handy for reproducing a corpus without a database.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..text.chunker import Chunk
from .corpus import MemoryCorpus


class InMemoryStore(MemoryCorpus):
    @classmethod
    def from_jsonl(cls, path: str | Path) -> "InMemoryStore":
        chunks: list[Chunk] = []
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    chunks.append(Chunk.from_dict(json.loads(line)))
        return cls(chunks)

    def find_quote_source(self, quote: str, docs: list[Chunk]) -> Chunk | None:
        from ..text.normalize import normalize_for_match

        q = normalize_for_match(quote)
        for chunk in docs:
            if q and q in normalize_for_match(chunk.text_display):
                return chunk
        return None
