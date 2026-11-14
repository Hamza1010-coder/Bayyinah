"""SQLite persistence.

One file holds everything the product knows: documents, chunks, the FTS5 index,
term document-frequencies, answered questions, contract reports, feedback and an
audit log.

Why SQLite and not Postgres: it is stdlib, it ships FTS5 (fast lexical BM25),
it survives restarts, and it makes the repo runnable with zero services. The
schema and the query shapes below are Postgres-compatible for the day this
outgrows a single box -- see docs/ARCHITECTURE.md.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS documents (
    doc_id          TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    issuer          TEXT DEFAULT '',
    version         TEXT DEFAULT '',
    url             TEXT DEFAULT '',
    lang            TEXT DEFAULT 'ar',
    synthetic       INTEGER DEFAULT 0,
    sha256          TEXT NOT NULL,
    filename        TEXT DEFAULT '',
    ingested_at     TEXT NOT NULL,
    provenance_json TEXT DEFAULT '{}',
    n_chunks        INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id     TEXT PRIMARY KEY,
    doc_id       TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    article_no   TEXT NOT NULL,
    chapter      TEXT DEFAULT '',
    page         INTEGER DEFAULT 0,
    lang         TEXT DEFAULT 'ar',
    text_display TEXT NOT NULL,
    text_norm    TEXT NOT NULL,
    url          TEXT DEFAULT '',
    synthetic    INTEGER DEFAULT 0,
    ord          INTEGER DEFAULT 0,
    vector       BLOB
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_chunks_article ON chunks(doc_id, article_no);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    chunk_id UNINDEXED,
    text_norm,
    tokenize = 'unicode61 remove_diacritics 0'
);

CREATE TABLE IF NOT EXISTS chunk_terms (
    chunk_id TEXT NOT NULL,
    term     TEXT NOT NULL,
    PRIMARY KEY (chunk_id, term)
);
CREATE INDEX IF NOT EXISTS idx_chunk_terms_term ON chunk_terms(term);

CREATE TABLE IF NOT EXISTS queries (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    ts               TEXT NOT NULL,
    question         TEXT NOT NULL,
    answer_json      TEXT NOT NULL,
    refusal_reason   TEXT,
    confidence       TEXT,
    latency_ms       REAL,
    cost_usd         REAL,
    model            TEXT,
    verification_ok  INTEGER,
    n_citations      INTEGER,
    actor            TEXT DEFAULT 'anonymous'
);
CREATE INDEX IF NOT EXISTS idx_queries_ts ON queries(ts DESC);

CREATE TABLE IF NOT EXISTS contracts (
    id             TEXT PRIMARY KEY,
    ts             TEXT NOT NULL,
    filename       TEXT NOT NULL,
    report_json    TEXT NOT NULL,
    counts_json    TEXT NOT NULL,
    redaction_json TEXT DEFAULT '{}',
    actor          TEXT DEFAULT 'anonymous'
);
CREATE INDEX IF NOT EXISTS idx_contracts_ts ON contracts(ts DESC);

CREATE TABLE IF NOT EXISTS feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id   TEXT NOT NULL,
    useful      INTEGER NOT NULL,
    comment     TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS audit (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    actor       TEXT DEFAULT 'anonymous',
    action      TEXT NOT NULL,
    detail_json TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts DESC);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    """Thread-safe-enough SQLite wrapper.

    sqlite3 connections are not thread-safe unless serialised; we open with
    check_same_thread=False and guard writes with a lock. Reads on a WAL
    database are fine concurrently.
    """

    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        with self._lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    # -- plumbing ---------------------------------------------------------
    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    def executemany(self, sql: str, rows: Iterable[Sequence[Any]]) -> None:
        with self._lock:
            self.conn.executemany(sql, rows)
            self.conn.commit()

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self.conn.execute(sql, params).fetchall())

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    # -- documents --------------------------------------------------------
    def upsert_document(self, **kw: Any) -> None:
        self.execute(
            """
            INSERT INTO documents
                (doc_id, title, issuer, version, url, lang, synthetic, sha256,
                 filename, ingested_at, provenance_json, n_chunks)
            VALUES (:doc_id, :title, :issuer, :version, :url, :lang, :synthetic,
                    :sha256, :filename, :ingested_at, :provenance_json, :n_chunks)
            ON CONFLICT(doc_id) DO UPDATE SET
                title=excluded.title, issuer=excluded.issuer, version=excluded.version,
                url=excluded.url, lang=excluded.lang, synthetic=excluded.synthetic,
                sha256=excluded.sha256, filename=excluded.filename,
                ingested_at=excluded.ingested_at,
                provenance_json=excluded.provenance_json, n_chunks=excluded.n_chunks
            """,
            {**kw, "provenance_json": json.dumps(kw.get("provenance_json") or {}, ensure_ascii=False)},
        )

    def documents(self) -> list[sqlite3.Row]:
        return self.query("SELECT * FROM documents ORDER BY title")

    def document(self, doc_id: str) -> sqlite3.Row | None:
        return self.query_one("SELECT * FROM documents WHERE doc_id = ?", (doc_id,))

    def delete_document(self, doc_id: str) -> None:
        chunk_ids = [r["chunk_id"] for r in self.query("SELECT chunk_id FROM chunks WHERE doc_id = ?", (doc_id,))]
        for cid in chunk_ids:
            self.delete_chunk(cid)
        self.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))

    # -- chunks -----------------------------------------------------------
    def add_chunk(self, chunk: dict, vector: list[float] | None = None) -> None:
        blob = None
        if vector:
            from array import array

            blob = array("f", vector).tobytes()
        self.execute(
            """
            INSERT OR REPLACE INTO chunks
                (chunk_id, doc_id, article_no, chapter, page, lang, text_display,
                 text_norm, url, synthetic, ord, vector)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                chunk["chunk_id"], chunk["doc_id"], str(chunk["article_no"]), chunk.get("chapter", ""),
                int(chunk.get("page") or 0), chunk.get("lang", "ar"), chunk["text_display"],
                chunk["text_norm"], chunk.get("url", ""), int(bool(chunk.get("synthetic"))),
                int(chunk.get("ord") or 0), blob,
            ),
        )
        self.execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (chunk["chunk_id"],))
        self.execute(
            "INSERT INTO chunks_fts (chunk_id, text_norm) VALUES (?, ?)",
            (chunk["chunk_id"], chunk["text_norm"]),
        )
        self.execute("DELETE FROM chunk_terms WHERE chunk_id = ?", (chunk["chunk_id"],))
        terms = sorted(set(chunk["text_norm"].split()))
        self.executemany(
            "INSERT OR IGNORE INTO chunk_terms (chunk_id, term) VALUES (?, ?)",
            [(chunk["chunk_id"], t) for t in terms if t],
        )

    def delete_chunk(self, chunk_id: str) -> None:
        self.execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (chunk_id,))
        self.execute("DELETE FROM chunk_terms WHERE chunk_id = ?", (chunk_id,))
        self.execute("DELETE FROM chunks WHERE chunk_id = ?", (chunk_id,))

    def chunks(self) -> list[sqlite3.Row]:
        return self.query("SELECT * FROM chunks ORDER BY ord, chunk_id")

    def chunk(self, chunk_id: str) -> sqlite3.Row | None:
        return self.query_one("SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,))

    def chunks_for_article(self, doc_id: str, article_no: str) -> list[sqlite3.Row]:
        return self.query(
            "SELECT * FROM chunks WHERE doc_id = ? AND article_no = ? ORDER BY ord",
            (doc_id, str(article_no)),
        )

    def count_chunks(self) -> int:
        row = self.query_one("SELECT COUNT(*) AS n FROM chunks")
        return int(row["n"]) if row else 0

    # -- lexical search ---------------------------------------------------
    def search_fts(self, tokens: Sequence[str], limit: int = 40) -> list[tuple[str, float]]:
        """FTS5 BM25. Returns (chunk_id, score) with higher = better."""
        clean = [t for t in tokens if t and '"' not in t]
        if not clean:
            return []
        match = " OR ".join(f'"{t}"' for t in clean[:24])
        try:
            rows = self.query(
                "SELECT chunk_id, bm25(chunks_fts) AS score FROM chunks_fts "
                "WHERE chunks_fts MATCH ? ORDER BY score LIMIT ?",
                (match, limit),
            )
        except sqlite3.OperationalError:
            return []
        return [(r["chunk_id"], -float(r["score"])) for r in rows]

    def document_frequencies(self) -> dict[str, int]:
        rows = self.query("SELECT term, COUNT(*) AS df FROM chunk_terms GROUP BY term")
        return {r["term"]: int(r["df"]) for r in rows}

    # -- queries / audit --------------------------------------------------
    def log_query(self, **kw: Any) -> int:
        cur = self.execute(
            """INSERT INTO queries
               (ts, question, answer_json, refusal_reason, confidence, latency_ms,
                cost_usd, model, verification_ok, n_citations, actor)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                kw.get("ts") or utcnow(), kw["question"], kw["answer_json"],
                kw.get("refusal_reason"), kw.get("confidence"), kw.get("latency_ms", 0.0),
                kw.get("cost_usd", 0.0), kw.get("model", ""),
                int(bool(kw.get("verification_ok"))), kw.get("n_citations", 0),
                kw.get("actor", "anonymous"),
            ),
        )
        return int(cur.lastrowid or 0)

    def recent_queries(self, limit: int = 50) -> list[sqlite3.Row]:
        return self.query("SELECT * FROM queries ORDER BY id DESC LIMIT ?", (limit,))

    def query_stats(self) -> dict[str, Any]:
        total = self.query_one("SELECT COUNT(*) n FROM queries")
        refused = self.query_one("SELECT COUNT(*) n FROM queries WHERE refusal_reason IS NOT NULL")
        avg = self.query_one("SELECT AVG(latency_ms) l, AVG(cost_usd) c FROM queries")
        return {
            "total": int(total["n"]) if total else 0,
            "refused": int(refused["n"]) if refused else 0,
            "avg_latency_ms": round(float(avg["l"] or 0), 1) if avg else 0.0,
            "avg_cost_usd": round(float(avg["c"] or 0), 6) if avg else 0.0,
        }

    def save_contract(self, **kw: Any) -> None:
        self.execute(
            """INSERT OR REPLACE INTO contracts
               (id, ts, filename, report_json, counts_json, redaction_json, actor)
               VALUES (?,?,?,?,?,?,?)""",
            (
                kw["id"], kw.get("ts") or utcnow(), kw["filename"],
                json.dumps(kw["report"], ensure_ascii=False),
                json.dumps(kw["counts"], ensure_ascii=False),
                json.dumps(kw.get("redaction") or {}, ensure_ascii=False),
                kw.get("actor", "anonymous"),
            ),
        )

    def contracts(self, limit: int = 50) -> list[sqlite3.Row]:
        return self.query("SELECT id, ts, filename, counts_json FROM contracts ORDER BY ts DESC LIMIT ?", (limit,))

    def contract(self, contract_id: str) -> sqlite3.Row | None:
        return self.query_one("SELECT * FROM contracts WHERE id = ?", (contract_id,))

    def add_feedback(self, target_type: str, target_id: str, useful: bool, comment: str = "") -> None:
        self.execute(
            "INSERT INTO feedback (ts, target_type, target_id, useful, comment) VALUES (?,?,?,?,?)",
            (utcnow(), target_type, str(target_id), int(useful), comment),
        )

    def feedback_stats(self) -> dict[str, Any]:
        row = self.query_one("SELECT COUNT(*) n, AVG(useful) u FROM feedback")
        return {"total": int(row["n"]) if row else 0, "useful_rate": round(float(row["u"] or 0), 3) if row else 0.0}

    def audit(self, action: str, detail: dict | None = None, actor: str = "anonymous") -> None:
        self.execute(
            "INSERT INTO audit (ts, actor, action, detail_json) VALUES (?,?,?,?)",
            (utcnow(), actor, action, json.dumps(detail or {}, ensure_ascii=False)),
        )

    def recent_audit(self, limit: int = 100) -> list[sqlite3.Row]:
        return self.query("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))

    def reset(self) -> None:
        """Danger: wipe all content, keep schema."""
        for table in ("chunk_terms", "chunks_fts", "chunks", "documents", "queries", "contracts", "feedback", "audit"):
            self.execute(f"DELETE FROM {table}")
