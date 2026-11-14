import unittest

from tests.support import ROOT  # noqa: F401  (ensures sys.path)
from bayyinah.text.normalize import (
    contains_normalized,
    content_tokens,
    normalize_for_index,
    normalize_for_match,
    strip_diacritics,
    tokenize,
    unify_digits,
)


class TestDiacritics(unittest.TestCase):
    def test_strips_harakat(self):
        self.assertEqual(strip_diacritics("الْمَادَّة"), "المادة")

    def test_display_text_is_not_mutated(self):
        original = "فترة التَّجربة"
        strip_diacritics(original)
        self.assertEqual(original, "فترة التَّجربة")


class TestDigits(unittest.TestCase):
    def test_arabic_indic_to_ascii(self):
        self.assertEqual(unify_digits("المادة ٨٤"), "المادة 84")

    def test_extended_arabic_indic(self):
        self.assertEqual(unify_digits("۹۰"), "90")


class TestLetterUnification(unittest.TestCase):
    def test_alef_forms_collapse(self):
        self.assertEqual(
            normalize_for_match("أجر"), normalize_for_match("اجر")
        )

    def test_ta_marbuta_survives_match_normalization(self):
        # Critical: the verifier must not treat 'خدمة' and 'خدمه' as identical.
        self.assertNotEqual(
            normalize_for_match("خدمة"), normalize_for_match("خدمه")
        )

    def test_ta_marbuta_folds_for_index(self):
        self.assertEqual(
            normalize_for_index("الخدمة"), normalize_for_index("الخدمه")
        )


class TestIndexNormalization(unittest.TestCase):
    def test_definite_article_stripped(self):
        self.assertEqual(
            normalize_for_index("الإجازة السنوية"),
            normalize_for_index("اجازة سنوية"),
        )

    def test_light_stemming_plurals(self):
        self.assertEqual(normalize_for_index("ساعات"), normalize_for_index("ساعة"))
        self.assertEqual(normalize_for_index("مكافآت"), normalize_for_index("مكافأة"))

    def test_arabic_punctuation_removed(self):
        # U+061F sits inside the Arabic block; a naive [^\w\u0600-\u06FF]
        # filter leaves it glued to the token.
        self.assertNotIn("؟", tokenize("ما هي المادة؟"))
        self.assertTrue(any(t.startswith("ماد") for t in tokenize("ما هي المادة؟")))


class TestContentTokens(unittest.TestCase):
    def test_stopwords_removed(self):
        tokens = content_tokens("ما هي مدة فترة التجربة في النظام؟")
        self.assertNotIn("ما", tokens)
        self.assertNotIn("هي", tokens)
        self.assertNotIn("في", tokens)
        self.assertTrue(any(t.startswith("تجرب") for t in tokens), tokens)


class TestContainsNormalized(unittest.TestCase):
    def test_matches_despite_diacritics(self):
        source = "يستحق العامل مكافأة نهاية الخدمة وفقاً للمادة (٨٤)."
        quote = "يستحق العامل مكافأة نهاية الخدمة وفقا للمادة (84)"
        self.assertTrue(contains_normalized(source, quote))

    def test_rejects_paraphrase(self):
        source = "يستحق العامل مكافأة نهاية الخدمة."
        quote = "يحصل العامل على تعويض عند انتهاء العمل."
        self.assertFalse(contains_normalized(source, quote))


if __name__ == "__main__":
    unittest.main()
