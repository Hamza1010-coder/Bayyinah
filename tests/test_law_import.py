import unittest

from tests.support import ROOT  # noqa: F401
from bayyinah.ingest.law_import import clean, import_bytes, strip_html
from bayyinah.text.chunker import split_articles

# Modelled on the Bureau of Experts web compilation: headings carry amendment
# badges and a "report an error" button that must never reach the corpus.
FIXTURE = """<html><body>
<h1>نظام العمل</h1>
<h2>الباب الأول: التعريفات</h2>
<p>المادة الأولى هل هناك خطأ؟ أبلغنا</p>
<p>يسمى هذا النظام نظام العمل.</p>
<p>المادة الثانية عشرةمعدلة — المرسوم الملكي رقم (م/46) بتاريخ 5/6/1436هـ (روجعت يدويًّا) هل هناك خطأ؟ أبلغنا</p>
<p>يلتزم كل صاحب عمل بإعداد لائحة لتنظيم العمل في منشأته وفق النموذج المعد من الوزارة.</p>
<p>المادة الثانية والعشرون هل هناك خطأ؟ أبلغنا</p>
<p>توفر الوزارة قنوات للتوظيف دون مقابل.</p>
<p>المادة المائة والثانية والعشرون هل هناك خطأ؟ أبلغنا</p>
<p>نص المادة بعد المائة.</p>
</body></html>"""


class TestStripAndClean(unittest.TestCase):
    def test_html_to_text_keeps_paragraphs(self):
        text = strip_html(FIXTURE)
        self.assertIn("يسمى هذا النظام نظام العمل", text)
        self.assertNotIn("<p>", text)

    def test_noise_lines_removed(self):
        cleaned = clean(strip_html(FIXTURE))
        self.assertNotIn("أبلغنا", cleaned)
        self.assertNotIn("معدلة", cleaned)
        self.assertIn("نظام العمل", cleaned)

    def test_inline_badge_removed(self):
        cleaned = clean("المادة الثانية عشرةمعدلة — المرسوم الملكي رقم (م/46)\nنص.")
        self.assertNotIn("المرسوم", cleaned)


class TestImport(unittest.TestCase):
    def setUp(self):
        self.text, self.report = import_bytes(FIXTURE.encode("utf-8"), "law.html")

    def test_counts_articles(self):
        self.assertEqual(self.report.articles, 4)

    def test_numbers_parsed_from_words(self):
        numbers = [n for n, _ in split_articles(self.text)]
        self.assertEqual(numbers, ["1", "12", "22", "122"])

    def test_first_and_last(self):
        self.assertEqual((self.report.first, self.report.last), ("1", "122"))

    def test_gaps_are_reported(self):
        self.assertIn("2", self.report.missing)

    def test_bodies_contain_no_editorial_chrome(self):
        for _, body in split_articles(self.text):
            self.assertNotIn("أبلغنا", body)
            self.assertNotIn("المرسوم", body)

    def test_warns_on_partial_document(self):
        self.assertTrue(any("252" in w for w in self.report.warnings))

    def test_plain_text_input_works(self):
        text, report = import_bytes("المادة الثالثة\nنص المادة الثالثة.".encode(), "law.txt")
        self.assertEqual(report.articles, 1)
        self.assertIn("نص المادة الثالثة", text)


class TestWordHeadingsInChunker(unittest.TestCase):
    def test_splits_on_word_numbers(self):
        text = "المادة الأولى\nنص أول.\n\nالمادة الثانية والعشرون\nنص ثانٍ."
        self.assertEqual([n for n, _ in split_articles(text)], ["1", "22"])

    def test_duplicate_number_gets_suffix(self):
        text = "المادة الحادية عشرة\nنص.\n\nالمادة الحادية عشرة (مكرر)\nنص مكرر."
        self.assertEqual([n for n, _ in split_articles(text)], ["11", "11م1"])

    def test_inline_body_is_kept(self):
        text = "المادة 84: يستحق العامل مكافأة نهاية الخدمة عند انتهاء العلاقة."
        articles = split_articles(text)
        self.assertEqual(len(articles), 1)
        self.assertIn("يستحق العامل", articles[0][1])

    def test_prose_mention_is_not_a_heading(self):
        text = "المادة التي تنظم الإجازة لم تُطبق.\nالمادة 5\nنص."
        numbers = [n for n, _ in split_articles(text)]
        self.assertNotIn("0", numbers)


if __name__ == "__main__":
    unittest.main()
