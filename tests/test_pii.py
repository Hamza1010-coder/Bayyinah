import unittest

from tests.support import ROOT  # noqa: F401
from bayyinah.text.pii import is_safe_to_send, redact


class TestRedaction(unittest.TestCase):
    def test_national_id(self):
        clean, report = redact("رقم الهوية 1234567890 لدى الموظف")
        self.assertNotIn("1234567890", clean)
        self.assertEqual(report.counts["NATIONAL_ID"], 1)

    def test_iban(self):
        clean, _ = redact("الحساب SA0380000000608010167519 لدى البنك")
        self.assertNotIn("SA0380000000608010167519", clean)

    def test_phone(self):
        clean, _ = redact("للتواصل 0551234567 أو +966555123456")
        self.assertNotIn("0551234567", clean)

    def test_email(self):
        clean, _ = redact("البريد hr@example.com")
        self.assertNotIn("hr@example.com", clean)

    def test_money_amount(self):
        clean, report = redact("الراتب 9,500 ريال سعودي")
        self.assertNotIn("9,500", clean)
        self.assertGreater(report.total, 0)

    def test_article_references_survive(self):
        # Over-redaction is a failure mode too: legal references must survive.
        clean, report = redact("وفقاً للمادة 84 من نظام العمل")
        self.assertIn("84", clean)
        self.assertTrue(report.clean)

    def test_is_safe_to_send(self):
        self.assertFalse(is_safe_to_send("هوية 1234567890"))
        self.assertTrue(is_safe_to_send("نص العقد خالٍ من المعرفات"))


if __name__ == "__main__":
    unittest.main()
