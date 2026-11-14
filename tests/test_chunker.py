import unittest

from tests.support import SAMPLE_LAW
from bayyinah.text.chunker import chunk_document, split_articles, split_long

EXPECTED = ["53", "60", "74", "80", "84", "85", "98", "109"]


class TestSplitArticles(unittest.TestCase):
    def setUp(self):
        self.text = SAMPLE_LAW.read_text(encoding="utf-8")
        self.articles = split_articles(self.text)

    def test_finds_all_articles_in_order(self):
        self.assertEqual([a for a, _ in self.articles], EXPECTED)

    def test_bodies_are_non_empty(self):
        for _, body in self.articles:
            self.assertTrue(body.strip())

    def test_body_excludes_next_heading(self):
        body = dict(self.articles)["53"]
        self.assertNotIn("المادة 60", body)

    def test_arabic_indic_numbers_are_canonicalized(self):
        text = "المادة ٨٤\nنص أول.\nالمادة ٨٥\nنص ثانٍ."
        self.assertEqual([a for a, _ in split_articles(text)], ["84", "85"])

    def test_english_translation_fallback(self):
        text = "Article 1\nFirst.\nArticle 2\nSecond."
        self.assertEqual([a for a, _ in split_articles(text)], ["1", "2"])


class TestChunking(unittest.TestCase):
    def setUp(self):
        self.text = SAMPLE_LAW.read_text(encoding="utf-8")
        self.chunks = chunk_document(self.text, doc_id="x", title="نظام العمل")

    def test_one_chunk_per_short_article(self):
        self.assertEqual(len(self.chunks), 8)

    def test_chunk_carries_article_number(self):
        self.assertEqual([c.article_no for c in self.chunks], EXPECTED)

    def test_heading_prepended_to_search_key_only(self):
        chunk = self.chunks[0]
        # text_norm is normalized, so assert on stems rather than raw words.
        self.assertIn("نظام", chunk.text_norm)
        self.assertIn("عمل", chunk.text_norm)
        self.assertNotIn("نظام", chunk.text_display)

    def test_display_text_is_verbatim_source(self):
        # The verifier quotes from text_display; it must not be normalized.
        chunk = self.chunks[0]
        self.assertIn(chunk.text_display[:40], self.text)

    def test_long_article_splits_but_keeps_article_number(self):
        body = " ".join(f"جملة رقم {i} في المادة الطويلة." for i in range(200))
        pieces = split_long(body, max_chars=400, overlap_chars=60)
        self.assertGreater(len(pieces), 1)
        self.assertTrue(all(len(p) <= 900 for p in pieces))

    def test_overlap_is_retained(self):
        body = " ".join(f"الفقرة {i} تحتوي على نص طويل نسبياً هنا." for i in range(80))
        pieces = split_long(body, max_chars=400, overlap_chars=80)
        self.assertEqual(len({p[:20] for p in pieces}), len(pieces))


if __name__ == "__main__":
    unittest.main()
