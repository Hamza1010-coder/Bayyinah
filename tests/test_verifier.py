import unittest

from tests.support import make_store
from bayyinah.generation.verifier import has_hard_failure, verify
from bayyinah.schemas import Answer, Citation

VERBATIM = "يستحق العامل عند انتهاء علاقة العمل مكافأة نهاية الخدمة"


class TestVerifier(unittest.TestCase):
    def setUp(self):
        self.store = make_store()

    def _answer(self, quote, article="84", doc_id="test_law", prose="نص"):
        return Answer(
            question="q",
            answer_ar=prose,
            citations=[Citation(doc_id=doc_id, article_no=article, quote=quote)],
        )

    def test_verbatim_quote_passes(self):
        problems = verify(self._answer(VERBATIM), self.store)
        self.assertFalse(has_hard_failure(problems), [p.kind for p in problems])

    def test_nonexistent_article_fails_hard(self):
        problems = verify(self._answer(VERBATIM, article="999"), self.store)
        self.assertTrue(has_hard_failure(problems))
        self.assertEqual(problems[0].kind, "article_not_found")

    def test_paraphrased_quote_fails_hard(self):
        paraphrase = "يجب على صاحب العمل دفع تعويض كامل للعامل عند ترك العمل"
        problems = verify(self._answer(paraphrase), self.store)
        self.assertTrue(has_hard_failure(problems))
        self.assertEqual(problems[0].kind, "quote_not_verbatim")

    def test_diacritics_and_alef_variants_still_pass(self):
        # Genuine orthographic variance (tashkeel, alef forms) must not fail a
        # quote. Note: 'ة' vs 'ه' is deliberately NOT tolerated -- see the
        # normalize_for_match docstring.
        variant = VERBATIM.replace("العمل", "العمَل").replace("عند", "عندَ")
        problems = verify(self._answer(variant), self.store)
        self.assertFalse(has_hard_failure(problems), [p.kind for p in problems])

    def test_empty_quote_fails_hard(self):
        problems = verify(self._answer("   "), self.store)
        self.assertTrue(has_hard_failure(problems))

    def test_uncited_article_reference_is_soft(self):
        answer = Answer(question="q", answer_ar="وفقاً للمادة 84 من النظام", citations=[])
        problems = verify(answer, self.store)
        self.assertTrue(any(p.kind == "uncited_article_reference" for p in problems))
        self.assertFalse(has_hard_failure(problems))

    def test_resolves_citation_without_doc_id(self):
        answer = Answer(
            question="q",
            citations=[Citation(doc_id="", article_no="84", quote=VERBATIM)],
        )
        self.assertFalse(has_hard_failure(verify(answer, self.store)))


if __name__ == "__main__":
    unittest.main()
