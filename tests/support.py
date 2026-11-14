"""Shared fixtures."""

from __future__ import annotations

import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEST_TMP = ROOT / "var" / "test-tmp"


class TempDir:
    """Workspace-local temporary directory.

    Deliberately NOT tempfile.mkdtemp: that creates a 0700 directory, which the
    process sandbox (running under a restricted token) cannot traverse. Creating
    the directory normally lets it inherit the workspace ACL.
    """

    def __init__(self) -> None:
        TEST_TMP.mkdir(parents=True, exist_ok=True)
        self.path = TEST_TMP / f"t{uuid.uuid4().hex[:10]}"
        self.path.mkdir()

    def __enter__(self) -> str:
        return str(self.path)

    def __exit__(self, *exc) -> None:
        shutil.rmtree(self.path, ignore_errors=True)


def tmpdir() -> TempDir:
    return TempDir()

from bayyinah.db import Database, utcnow  # noqa: E402
from bayyinah.retrieval.embed import HashingEmbedder  # noqa: E402
from bayyinah.retrieval.store import InMemoryStore  # noqa: E402
from bayyinah.text.chunker import chunk_document  # noqa: E402

SAMPLE_LAW = ROOT / "corpora/raw/labor_law_sample_SYNTHETIC.txt"

SAMPLE_CONTRACT = "\n".join(
    [
        "البند 1: يلتزم الطرف الثاني بالعمل لدى الطرف الأول بوظيفة أخصائي موارد بشرية.",
        "البند 2: تكون فترة التجربة ستة أشهر قابلة للتمديد.",
        "البند 3: تتقاضى الموظفة أجراً شهرياً قدره 9,500 ريال سعودي.",
        "البند 4: يوافق الطرف الثاني على التنازل عن مكافأة نهاية الخدمة.",
        "البند 5: تكون ساعات العمل 56 ساعة أسبوعياً.",
        "البند 6: يستحق الموظف إجازة سنوية مدتها 15 يوماً.",
        "البند 7: يجوز للطرف الأول إنهاء العقد دون إشعار في أي وقت.",
    ]
)


def law_chunks(doc_id: str = "test_law") -> list:
    text = SAMPLE_LAW.read_text(encoding="utf-8")
    return chunk_document(text, doc_id=doc_id, title="نظام العمل", synthetic=True)


def make_store() -> InMemoryStore:
    """In-memory corpus, no database. Fast; used by pure-logic tests."""
    return InMemoryStore(law_chunks())


def make_db() -> Database:
    """SQLite corpus seeded with the fixture, for persistence-path tests."""
    db = Database(":memory:")
    chunks = law_chunks()
    embedder = HashingEmbedder()
    vectors = embedder.embed([c.text_norm for c in chunks])
    db.upsert_document(
        doc_id="test_law",
        title="نظام العمل",
        issuer="fixture",
        version="test",
        url="",
        lang="ar",
        synthetic=1,
        sha256="fixture",
        filename=SAMPLE_LAW.name,
        ingested_at=utcnow(),
        provenance_json={"source": "test"},
        n_chunks=len(chunks),
    )
    for ordinal, (chunk, vector) in enumerate(zip(chunks, vectors)):
        payload = chunk.to_dict()
        payload["ord"] = ordinal
        db.add_chunk(payload, vector)
    return db
