import unittest

from tests.support import make_db
from bayyinah.db import Database


class TestDocuments(unittest.TestCase):
    def setUp(self):
        self.db = make_db()

    def test_document_round_trip(self):
        rows = self.db.documents()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["doc_id"], "test_law")
        self.assertEqual(rows[0]["n_chunks"], 8)

    def test_chunks_are_counted(self):
        self.assertEqual(self.db.count_chunks(), 8)

    def test_article_lookup(self):
        rows = self.db.chunks_for_article("test_law", "84")
        self.assertEqual(len(rows), 1)
        self.assertIn("مكافأة نهاية الخدمة", rows[0]["text_display"])

    def test_delete_document_cascades(self):
        self.db.delete_document("test_law")
        self.assertEqual(self.db.count_chunks(), 0)
        self.assertEqual(self.db.documents(), [])
        # FTS rows must be gone too, or search returns ghosts.
        self.assertEqual(self.db.search_fts(["مكاف"]), [])


class TestSearch(unittest.TestCase):
    def setUp(self):
        self.db = make_db()

    def test_fts_finds_article(self):
        hits = self.db.search_fts(["اجاز"])
        self.assertTrue(hits)
        row = self.db.chunk(hits[0][0])
        self.assertEqual(row["article_no"], "109")

    def test_fts_scores_descending(self):
        hits = self.db.search_fts(["مكاف", "خدم"])
        scores = [s for _, s in hits]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_fts_handles_quotes_in_query(self):
        self.assertEqual(self.db.search_fts(['"']), [])

    def test_document_frequencies(self):
        df = self.db.document_frequencies()
        self.assertGreater(df.get("مكاف", 0), 0)
        self.assertLessEqual(df["مكاف"], 8)


class TestQueriesAndAudit(unittest.TestCase):
    def test_log_and_stats(self):
        db = Database(":memory:")
        qid = db.log_query(question="q", answer_json="{}", latency_ms=12.0, cost_usd=0.001)
        self.assertGreater(qid, 0)
        stats = db.query_stats()
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["avg_latency_ms"], 12.0)

    def test_audit_rows(self):
        db = Database(":memory:")
        db.audit("test_action", {"a": 1})
        rows = db.recent_audit()
        self.assertEqual(rows[0]["action"], "test_action")
        self.assertIn('"a": 1', rows[0]["detail_json"])

    def test_feedback_stats(self):
        db = Database(":memory:")
        db.add_feedback("query", "1", True)
        db.add_feedback("query", "2", False)
        self.assertEqual(db.feedback_stats()["useful_rate"], 0.5)

    def test_reset_clears_content(self):
        db = make_db()
        db.reset()
        self.assertEqual(db.count_chunks(), 0)
        self.assertEqual(db.documents(), [])


if __name__ == "__main__":
    unittest.main()
