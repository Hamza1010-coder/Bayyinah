import unittest

from tests.support import ROOT  # noqa: F401
from bayyinah.calc.eos import base_award, end_of_service, resignation_fraction


class TestBaseAward(unittest.TestCase):
    def test_first_five_years_half_month_each(self):
        self.assertEqual(base_award(6000, 3), 9000)     # 3 * 0.5 * 6000
        self.assertEqual(base_award(6000, 5), 15000)    # 5 * 0.5 * 6000

    def test_beyond_five_years_full_month(self):
        self.assertEqual(base_award(6000, 7), 27000)    # 15000 + 2 * 6000
        self.assertEqual(base_award(6000, 12), 57000)   # 15000 + 7 * 6000

    def test_zero_and_negative(self):
        self.assertEqual(base_award(0, 5), 0)
        self.assertEqual(base_award(6000, 0), 0)


class TestResignationBands(unittest.TestCase):
    def test_under_two_years_nothing(self):
        self.assertEqual(resignation_fraction(1.0), (0.0, "0"))

    def test_two_to_five_years_one_third(self):
        fraction, label = resignation_fraction(3.0)
        self.assertAlmostEqual(fraction, 1 / 3)
        self.assertEqual(label, "1/3")

    def test_five_to_ten_years_two_thirds(self):
        fraction, _ = resignation_fraction(7.0)
        self.assertAlmostEqual(fraction, 2 / 3)

    def test_over_ten_years_full(self):
        self.assertEqual(resignation_fraction(12.0), (1.0, "1"))


class TestEndOfService(unittest.TestCase):
    def test_resignation_three_years(self):
        calc = end_of_service(6000, 3, "resignation")
        self.assertAlmostEqual(calc.result, 3000.0)   # 9000 * 1/3
        self.assertEqual(calc.formula_ref, "art_84+art_85")
        self.assertEqual(len(calc.trace), 2)

    def test_resignation_under_two_years(self):
        self.assertEqual(end_of_service(6000, 1, "resignation").result, 0.0)

    def test_resignation_seven_years(self):
        calc = end_of_service(6000, 7, "resignation")
        self.assertAlmostEqual(calc.result, 18000.0)  # 27000 * 2/3

    def test_termination_pays_full(self):
        self.assertAlmostEqual(end_of_service(6000, 3, "termination").result, 9000.0)

    def test_dismissal_for_cause_pays_nothing(self):
        self.assertEqual(end_of_service(6000, 3, "article_80").result, 0.0)

    def test_trace_is_human_readable(self):
        calc = end_of_service(6000, 3, "resignation")
        # Trace is shown to end users; it uses Arabic-Indic numerals.
        self.assertTrue(any("٨٤" in line for line in calc.trace))


if __name__ == "__main__":
    unittest.main()
