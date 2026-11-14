import unittest

from tests.support import make_db
from bayyinah.retrieval.corpus import SqliteCorpus


class TestSqliteCorpus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = SqliteCorpus(make_db())

    def test_loads_chunks(self):
        self.assertEqual(len(self.corpus), 8)

    def test_leave_question_ranks_109_first(self):
        hits = self.corpus.search("كم يوم إجازة سنوية للعامل؟", k=3)
        self.assertEqual(hits[0][0].article_no, "109")

    def test_probation_question_ranks_53_first(self):
        hits = self.corpus.search("ما هي فترة التجربة القصوى؟", k=3)
        self.assertEqual(hits[0][0].article_no, "53")

    def test_end_of_service_question_hits_84_or_85(self):
        hits = self.corpus.search("كم مكافأة نهاية الخدمة إذا استقلت؟", k=3)
        self.assertIn(hits[0][0].article_no, {"84", "85"})

    def test_get_article(self):
        chunk = self.corpus.get_article("test_law", "84")
        self.assertIsNotNone(chunk)
        self.assertIn("مكافأة", chunk.text_display)

    def test_get_article_unknown(self):
        self.assertIsNone(self.corpus.get_article("test_law", "999"))

    def test_idf_prefers_rare_terms(self):
        # "مكاف" is in 3 articles, "خدم" in most: rare must score higher.
        self.assertGreater(self.corpus.idf("مكاف"), self.corpus.idf("خدم"))

    def test_idf_unknown_term_is_high(self):
        self.assertGreater(self.corpus.idf("زبرجد"), self.corpus.idf("خدم"))

    def test_reload_picks_up_new_chunks(self):
        from tests.support import law_chunks
        from bayyinah.db import utcnow
        from bayyinah.retrieval.embed import HashingEmbedder

        db = make_db()
        corpus = SqliteCorpus(db)
        before = len(corpus)
        embedder = HashingEmbedder()
        db.upsert_document(
            doc_id="extra", title="إضافي", issuer="", version="", url="", lang="ar",
            synthetic=1, sha256="x", filename="extra.txt", ingested_at=utcnow(),
            provenance_json={}, n_chunks=1,
        )
        for chunk in law_chunks(doc_id="extra"):
            payload = chunk.to_dict()
            payload["ord"] = 0
            db.add_chunk(payload, embedder.embed_one(chunk.text_norm))
        corpus.reload()
        self.assertGreater(len(corpus), before)

    def test_empty_corpus_search(self):
        from bayyinah.db import Database

        empty = SqliteCorpus(Database(":memory:"))
        self.assertEqual(empty.search("anything"), [])


if __name__ == "__main__":
    unittest.main()
