import unittest

from tests.support import ROOT  # noqa: F401
from bayyinah.text.arabic_numbers import parse_number


class TestParseNumber(unittest.TestCase):
    def test_units(self):
        self.assertEqual(parse_number("الأولى"), 1)
        self.assertEqual(parse_number("الثانية"), 2)
        self.assertEqual(parse_number("العاشرة"), 10)

    def test_teens(self):
        self.assertEqual(parse_number("الحادية عشرة"), 11)
        self.assertEqual(parse_number("التاسعة عشرة"), 19)

    def test_compound_tens(self):
        self.assertEqual(parse_number("الثانية والعشرون"), 22)
        self.assertEqual(parse_number("الحادية والخمسون"), 51)
        self.assertEqual(parse_number("التسعون"), 90)

    def test_hundreds(self):
        self.assertEqual(parse_number("المائة"), 100)
        self.assertEqual(parse_number("المائة والثانية والعشرون"), 122)
        self.assertEqual(parse_number("المائتان"), 200)

    def test_digits_both_scripts(self):
        self.assertEqual(parse_number("84"), 84)
        self.assertEqual(parse_number("٨٤"), 84)
        self.assertEqual(parse_number("( ٢٢٦ )"), 226)

    def test_badges_are_ignored(self):
        # Real headings look like this; the badge is glued to the number.
        self.assertEqual(parse_number("الثانية عشرةمعدلة — المرسوم الملكي رقم (م/46)"), 12)
        self.assertEqual(parse_number("الحادية عشرة (مكرر)"), 11)
        self.assertEqual(parse_number("الثالثة هل هناك خطأ؟ أبلغنا"), 3)

    def test_prose_is_not_a_number(self):
        self.assertIsNone(parse_number("التي تنظم العلاقة بين الطرفين"))
        self.assertIsNone(parse_number(""))


if __name__ == "__main__":
    unittest.main()
