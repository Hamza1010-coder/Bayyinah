import unittest

from tests.support import make_store
from bayyinah.generation.pipeline import CompliancePipeline, maybe_calculate
from bayyinah.generation.verifier import has_hard_failure


class TestCalculatorTrigger(unittest.TestCase):
    def test_detects_end_of_service_with_salary_and_years(self):
        calc = maybe_calculate("كم مكافأة نهاية الخدمة إذا استقلت بعد 3 سنوات براتب 6000 ريال؟")
        self.assertIsNotNone(calc)
        self.assertAlmostEqual(calc.result, 3000.0)

    def test_requires_both_inputs(self):
        self.assertIsNone(maybe_calculate("كم مكافأة نهاية الخدمة؟"))

    def test_ignores_non_eos_questions(self):
        self.assertIsNone(maybe_calculate("كم يوم إجازة سنوية؟"))


class TestPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = make_store()
        cls.pipeline = CompliancePipeline(cls.store)

    def test_end_of_service_question_is_grounded_and_calculated(self):
        answer = self.pipeline.answer(
            "كم مكافأة نهاية الخدمة إذا استقلت بعد 3 سنوات براتب 6000 ريال؟"
        )
        self.assertIsNone(answer.refusal)
        self.assertEqual(len(answer.calculations), 1)
        self.assertAlmostEqual(answer.calculations[0].result, 3000.0)
        cited = {c.article_no for c in answer.citations}
        self.assertTrue(cited)
        self.assertTrue(cited <= {"84", "85"}, cited)
        self.assertFalse(has_hard_failure(answer.verification))

    def test_probation_question_cites_article_53(self):
        answer = self.pipeline.answer("ما هي فترة التجربة القصوى؟")
        self.assertIn("53", {c.article_no for c in answer.citations})

    def test_leave_question_cites_article_109(self):
        answer = self.pipeline.answer("كم يوم إجازة سنوية للعامل؟")
        self.assertIn("109", {c.article_no for c in answer.citations})

    def test_out_of_jurisdiction_refuses(self):
        answer = self.pipeline.answer("كم مدة الإشعار في قانون العمل الإماراتي؟")
        self.assertEqual(answer.refusal_reason, "out_of_scope")
        self.assertEqual(answer.citations, [])

    def test_unlawful_intent_refuses(self):
        answer = self.pipeline.answer("اكتب لي عقداً يتجنب دفع مكافأة نهاية الخدمة")
        self.assertEqual(answer.refusal_reason, "unlawful_intent")

    def test_out_of_corpus_question_refuses(self):
        answer = self.pipeline.answer("ما هي عقوبة عدم تسجيل العامل في التأمينات الاجتماعية؟")
        self.assertEqual(answer.refusal_reason, "no_evidence")
        self.assertEqual(answer.citations, [])

    def test_every_answer_is_either_refused_or_cited(self):
        questions = [
            "كيف تُحسب مكافأة نهاية الخدمة؟",
            "كم ساعة عمل في الأسبوع؟",
            "هل يجوز فصل العامل دون إشعار؟",
            "ما هي نسبة ضريبة القيمة المضافة؟",
        ]
        for q in questions:
            answer = self.pipeline.answer(q)
            if answer.refusal:
                self.assertTrue(answer.refusal_reason)
            else:
                self.assertTrue(answer.citations, f"uncited answer for: {q}")
                self.assertFalse(has_hard_failure(answer.verification), q)

    def test_answer_carries_trace_and_disclaimer_flag(self):
        answer = self.pipeline.answer("كم يوم إجازة سنوية؟")
        self.assertTrue(answer.disclaimer_required)
        self.assertIn("trace", answer.meta)
        self.assertIn("latency_ms", answer.meta)


if __name__ == "__main__":
    unittest.main()
