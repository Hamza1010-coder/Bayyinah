import unittest
from pathlib import Path

from tests.support import SAMPLE_CONTRACT, make_store, tmpdir
from bayyinah.contracts.analyzer import ContractAnalyzer
from bayyinah.contracts.report import to_docx, to_html, to_markdown


class TestAnalyzer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = make_store()
        cls.analyzer = ContractAnalyzer(cls.corpus)
        cls.result = cls.analyzer.analyze(SAMPLE_CONTRACT, filename="عقد.pdf")

    def test_counts(self):
        counts = self.result.report.counts()
        self.assertEqual(counts["non_compliant"], 4)
        self.assertEqual(counts["risky"], 1)

    def test_coverage_reported(self):
        self.assertEqual(self.result.coverage["clauses"], 7)
        self.assertEqual(self.result.coverage["covered_by_rules"], 5)

    def test_redaction_happens_before_analysis(self):
        self.assertGreater(sum(self.result.redaction.values()), 0)

    def test_pii_absent_from_findings(self):
        for finding in self.result.report.findings:
            self.assertNotIn("9,500", finding.clause_text)


class TestReports(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        corpus = make_store()
        cls.report = ContractAnalyzer(corpus).analyze(SAMPLE_CONTRACT, filename="عقد.pdf").report

    def test_markdown_contains_verdicts_and_disclaimer(self):
        md = to_markdown(self.report)
        self.assertIn("مخالف", md)
        self.assertIn("استشارة قانونية", md)
        self.assertIn("المادة 53", md)

    def test_html_is_standalone_rtl(self):
        html = to_html(self.report)
        self.assertIn('dir="rtl"', html)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("المادة 84", html)

    def test_html_escapes_input(self):
        corpus = make_store()
        report = ContractAnalyzer(corpus).analyze(
            "البند 1: <script>alert(1)</script> فترة التجربة ستة أشهر.", filename="x.txt"
        ).report
        self.assertNotIn("<script>alert(1)</script>", to_html(report))

    def test_docx_export(self):
        try:
            import docx  # noqa: F401
        except ImportError:
            self.skipTest("python-docx not installed")
        with tmpdir() as tmp:
            out = to_docx(self.report, Path(tmp) / "report.docx")
            self.assertTrue(out.exists())
            self.assertGreater(out.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()


