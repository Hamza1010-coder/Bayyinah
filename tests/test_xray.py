import unittest

from tests.support import SAMPLE_CONTRACT, make_store
from bayyinah.contracts.xray import analyze, segment_clauses


class TestSegmentation(unittest.TestCase):
    def test_splits_on_bnd_markers(self):
        clauses = segment_clauses(SAMPLE_CONTRACT)
        self.assertEqual(len(clauses), 7)
        self.assertTrue(clauses[0][0].startswith("c-"))

    def test_falls_back_to_paragraphs(self):
        text = "فقرة أولى طويلة بما يكفي للتحليل السريع.\n\nفقرة ثانية طويلة أيضاً بما يكفي."
        clauses = segment_clauses(text)
        self.assertEqual(len(clauses), 2)


class TestAnalysis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = make_store()
        cls.report = analyze(SAMPLE_CONTRACT, cls.store)

    def test_finds_the_four_hard_violations(self):
        counts = self.report.counts()
        self.assertEqual(counts["non_compliant"], 4, counts)

    def test_flags_probation_over_ninety_days(self):
        hit = [f for f in self.report.findings if f.clause_id == "c-002"]
        self.assertEqual(hit[0].verdict, "non_compliant")
        self.assertEqual(hit[0].citation.article_no, "53")

    def test_flags_end_of_service_waiver(self):
        hit = [f for f in self.report.findings if f.clause_id == "c-004"][0]
        self.assertEqual(hit.citation.article_no, "84")

    def test_flags_excess_weekly_hours(self):
        hit = [f for f in self.report.findings if f.clause_id == "c-005"][0]
        self.assertEqual(hit.citation.article_no, "98")

    def test_flags_short_annual_leave(self):
        hit = [f for f in self.report.findings if f.clause_id == "c-006"][0]
        self.assertEqual(hit.citation.article_no, "109")

    def test_flags_termination_without_notice_as_risky(self):
        hit = [f for f in self.report.findings if f.clause_id == "c-007"][0]
        self.assertEqual(hit.verdict, "risky")

    def test_benign_clause_is_not_flagged(self):
        hit = [f for f in self.report.findings if f.clause_id == "c-001"][0]
        self.assertEqual(hit.verdict, "not_covered")

    def test_findings_carry_a_citation_quote(self):
        for finding in self.report.findings:
            if finding.verdict != "not_covered":
                self.assertIsNotNone(finding.citation)
                self.assertTrue(finding.citation.quote)


if __name__ == "__main__":
    unittest.main()
