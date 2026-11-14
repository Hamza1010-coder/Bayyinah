"""Ingestion: file -> chunks -> database.

Idempotent by content hash: re-ingesting an unchanged file is a no-op, and
re-ingesting a changed file replaces that document's chunks atomically enough
for a single-user product.

Every run writes an audit row. Provenance is not optional here -- if a reviewer
cannot tell where a quote came from, the quote is worthless.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..db import Database, utcnow
from ..retrieval.embed import HashingEmbedder
from ..text.chunker import chunk_document
from .loaders import SUPPORTED, LoaderError, load


@dataclass
class IngestResult:
    doc_id: str
    filename: str
    status: str                     # created | updated | unchanged | failed
    chunks: int = 0
    articles: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "filename": self.filename,
            "status": self.status,
            "chunks": self.chunks,
            "articles": self.articles,
            "warnings": self.warnings,
            "error": self.error,
        }


def _slug(text: str) -> str:
    text = re.sub(r"[^\w\u0600-\u06FF]+", "_", text, flags=re.UNICODE)
    return text.strip("_").lower()[:64] or "document"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def ingest_document(
    db: Database,
    path: str | Path,
    *,
    doc_id: str | None = None,
    title: str | None = None,
    issuer: str = "",
    version: str = "",
    url: str = "",
    lang: str = "ar",
    synthetic: bool | None = None,
    embedder: HashingEmbedder | None = None,
    actor: str = "cli",
) -> IngestResult:
    p = Path(path)
    derived_id = doc_id or _slug(p.stem)
    try:
        loaded = load(p)
    except LoaderError as exc:
        db.audit("ingest_failed", {"file": p.name, "error": str(exc)}, actor=actor)
        return IngestResult(doc_id=derived_id, filename=p.name, status="failed", error=str(exc))

    digest = _sha256(p)
    existing = db.document(derived_id)
    if existing and existing["sha256"] == digest and existing["n_chunks"]:
        return IngestResult(
            doc_id=derived_id,
            filename=p.name,
            status="unchanged",
            chunks=int(existing["n_chunks"]),
        )

    is_synthetic = synthetic
    if is_synthetic is None:
        is_synthetic = "synthetic" in p.name.lower() or "fixture" in p.name.lower()

    # Replace previous chunks for this doc so re-ingest never duplicates.
    if existing:
        db.delete_document(derived_id)

    chunks = chunk_document(
        loaded.text,
        doc_id=derived_id,
        lang=lang,
        title=title or p.stem,
        url=url,
        synthetic=bool(is_synthetic),
    )
    if not chunks:
        return IngestResult(doc_id=derived_id, filename=p.name, status="failed", error="no chunks produced")

    embedder = embedder or HashingEmbedder()
    vectors = embedder.embed([c.text_norm for c in chunks])

    db.upsert_document(
        doc_id=derived_id,
        title=title or p.stem,
        issuer=issuer,
        version=version,
        url=url,
        lang=lang,
        synthetic=int(bool(is_synthetic)),
        sha256=digest,
        filename=p.name,
        ingested_at=utcnow(),
        provenance_json={"source_file": p.name, "kind": loaded.kind, "pages": loaded.pages},
        n_chunks=len(chunks),
    )
    for ordinal, (chunk, vector) in enumerate(zip(chunks, vectors)):
        payload = chunk.to_dict()
        payload["ord"] = ordinal
        db.add_chunk(payload, vector)

    result = IngestResult(
        doc_id=derived_id,
        filename=p.name,
        status="updated" if existing else "created",
        chunks=len(chunks),
        articles=[c.article_no for c in chunks],
        warnings=list(loaded.warnings),
    )
    db.audit("ingest", result.to_dict(), actor=actor)
    return result


SKIP_NAMES = {"readme", "license", "licence", "changelog", "contributing", "notes"}


def _is_corpus_file(path: Path) -> bool:
    if path.suffix.lower() not in SUPPORTED:
        return False
    stem = path.stem.lower()
    if stem in SKIP_NAMES or stem.startswith(("readme", "_", ".")):
        return False
    return True


def ingest_directory(
    db: Database,
    directory: str | Path,
    *,
    embedder: HashingEmbedder | None = None,
    actor: str = "cli",
) -> list[IngestResult]:
    folder = Path(directory)
    files = sorted(p for p in folder.iterdir() if p.is_file() and _is_corpus_file(p))
    return [ingest_document(db, f, embedder=embedder, actor=actor) for f in files]
