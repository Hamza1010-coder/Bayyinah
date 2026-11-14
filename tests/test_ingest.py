import unittest
from pathlib import Path

from tests.support import SAMPLE_LAW, TEST_TMP, make_db, tmpdir
from bayyinah.ingest.loaders import LoaderError, load, load_bytes
from bayyinah.ingest.pipeline import ingest_directory, ingest_document


class TestLoaders(unittest.TestCase):
    def test_text_file(self):
        doc = load(SAMPLE_LAW)
        self.assertEqual(doc.kind, "text")
        self.assertIn("المادة 84", doc.text)

    def test_load_bytes_matches_load(self):
        raw = SAMPLE_LAW.read_bytes()
        self.assertEqual(load_bytes(raw, SAMPLE_LAW.name).text, load(SAMPLE_LAW).text)

    def test_missing_file(self):
        with self.assertRaises(LoaderError):
            load("does/not/exist.txt")

    def test_unsupported_extension(self):
        with self.assertRaises(LoaderError):
            load_bytes(b"data", "file.xyz")

    def test_pdf_without_pypdf_is_actionable(self):
        try:
            import pypdf  # noqa: F401
            self.skipTest("pypdf installed")
        except ImportError:
            pass
        with self.assertRaises(LoaderError) as ctx:
            load_bytes(b"%PDF-1.4 fake", "x.pdf")
        self.assertIn("pypdf", str(ctx.exception))

    def test_empty_file(self):
        with self.assertRaises(LoaderError):
            load_bytes(b"   ", "empty.txt")


class TestIngest(unittest.TestCase):
    def setUp(self):
        self.db = make_db()

    def test_ingest_creates_document(self):
        with tmpdir() as tmp:
            target = Path(tmp) / "law.txt"
            target.write_text(SAMPLE_LAW.read_text(encoding="utf-8"), encoding="utf-8")
            result = ingest_document(self.db, target, doc_id="law2", title="نظام")
        self.assertEqual(result.status, "created")
        self.assertEqual(result.chunks, 8)
        self.assertIn("84", result.articles)

    def test_reingest_unchanged_is_noop(self):
        with tmpdir() as tmp:
            target = Path(tmp) / "law.txt"
            target.write_text(SAMPLE_LAW.read_text(encoding="utf-8"), encoding="utf-8")
            first = ingest_document(self.db, target, doc_id="law2")
            second = ingest_document(self.db, target, doc_id="law2")
        self.assertEqual(first.status, "created")
        self.assertEqual(second.status, "unchanged")

    def test_reingest_changed_replaces_chunks(self):
        with tmpdir() as tmp:
            target = Path(tmp) / "law.txt"
            target.write_text(SAMPLE_LAW.read_text(encoding="utf-8"), encoding="utf-8")
            ingest_document(self.db, target, doc_id="law2")
            target.write_text("المادة 1\nنص جديد قصير للمادة الأولى فقط في العقد.", encoding="utf-8")
            result = ingest_document(self.db, target, doc_id="law2")
        self.assertEqual(result.status, "updated")
        self.assertEqual(len(self.db.chunks_for_article("law2", "1")), 1)
        self.assertEqual(self.db.chunks_for_article("law2", "84"), [])

    def test_directory_skips_readme(self):
        with tmpdir() as tmp:
            folder = Path(tmp)
            (folder / "law.txt").write_text("المادة 1\nنص للمادة الأولى هنا.", encoding="utf-8")
            (folder / "README.md").write_text("# docs", encoding="utf-8")
            results = ingest_directory(self.db, folder)
        names = [r.filename for r in results]
        self.assertIn("law.txt", names)
        self.assertNotIn("README.md", names)

    def test_failed_load_is_reported_not_raised(self):
        with tmpdir() as tmp:
            target = Path(tmp) / "empty.txt"
            target.write_text("   ", encoding="utf-8")
            result = ingest_document(self.db, target)
        self.assertEqual(result.status, "failed")
        self.assertTrue(result.error)

    def test_audit_rows_written(self):
        with tmpdir() as tmp:
            target = Path(tmp) / "law.txt"
            target.write_text(SAMPLE_LAW.read_text(encoding="utf-8"), encoding="utf-8")
            ingest_document(self.db, target, doc_id="law2")
        actions = [r["action"] for r in self.db.recent_audit()]
        self.assertIn("ingest", actions)


class TestDocxIngest(unittest.TestCase):
    def test_docx_round_trip(self):
        try:
            import docx  # type: ignore
        except ImportError:
            self.skipTest("python-docx not installed")

        with tmpdir() as tmp:
            path = Path(tmp) / "contract.docx"
            document = docx.Document()
            document.add_paragraph("البند 1: فترة التجربة ستة أشهر.")
            document.add_paragraph("البند 2: ساعات العمل 56 ساعة أسبوعياً.")
            document.save(str(path))
            loaded = load(path)
        self.assertIn("فترة التجربة", loaded.text)
        self.assertEqual(loaded.kind, "docx")


if __name__ == "__main__":
    unittest.main()
