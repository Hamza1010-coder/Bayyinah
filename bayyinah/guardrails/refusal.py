"""Refusal policy: the product's most underrated feature.

Three classes of request must never be answered from this corpus:

1. Out of jurisdiction   -- UAE, Egypt, Qatar labour law.
2. Unlawful intent       -- "draft a contract that avoids end-of-service pay".
3. No evidence           -- the corpus genuinely does not cover it.

Classes 1 and 2 are matched cheaply and deterministically *before* retrieval,
because a retrieval score will happily find a semantically nearby article and
the model will happily answer from it.
"""

from __future__ import annotations

import re

OTHER_JURISDICTIONS = [
    "الإمارات", "الامارات", "دبي", "أبوظبي", "ابوظبي", "قطر", "الكويت", "البحرين",
    "عمان", "الأردن", "الاردن", "مصر", "لبنان", "العراق", "المغرب", "تونس",
    "uae", "dubai", "qatar", "kuwait", "bahrain", "egypt", "jordan", "oman",
]

UNLAWFUL_PATTERNS = [
    r"(?:عقد|اتفاق|صياغة).{0,25}(?:يتجنب|يتحايل|يتفادى|يهرب)",
    r"(?:تجنب|تهرب|تحايل).{0,25}(?:المكافأة|نهاية الخدمة|التأمينات|الضريبة)",
    r"(?:بدون|دون)\s+(?:دفع|تسجيل|تأمين)",
    r"أخفي\s+(?:ال)?(?:عامل|موظف|راتب|عقد)",
    r"draft.{0,20}(?:avoid|evade|circumvent).{0,20}(?:end of service|gosi|tax)",
]

_CONTEXT_HINTS = [
    "نظام العمل", "المادة", "مادة", "عامل", "عاملين", "موظف", "موظفين", "صاحب العمل",
    "عقد عمل", "مكافأة", "استقالة", "فصل", "إجازة", "اجازة", "أجر", "اجر",
    "ساعات العمل", "فترة التجربة", "تجربة", "تأمينات", "التأمينات", "نهاية الخدمة",
    "labor", "labour", "employee", "employer", "article", "wage", "salary",
    "resignation", "termination", "probation", "leave", "gosi",
]

_refusal_out_of_scope_ar = (
    "لا أستطيع الإجابة عن هذا السؤال: نطاقي يقتصر على نظام العمل السعودي "
    "ولائحته التنفيذية وأنظمة التأمينات الاجتماعية. للأنظمة في الدول الأخرى "
    "يرجى الرجوع إلى الجهة المختصة في تلك الدولة."
)
_refusal_unlawful_ar = (
    "لا يمكنني المساعدة في صياغة ترتيب يخالف نظام العمل. يمكنني بدلاً من ذلك "
    "توضيح ما يسمح به النظام، أو كيفية تحقيق هدفك المشروع بطريقة متوافقة."
)
_refusal_no_evidence_ar = (
    "لم أجد مادة نظامية في المصادر المتاحة تدعم إجابة موثوقة على هذا السؤال. "
    "لتفادي إعطائك معلومة غير دقيقة، سأحيلك إلى مختص."
)


def detect_jurisdiction(question: str) -> str | None:
    q = question.lower()
    for j in OTHER_JURISDICTIONS:
        if j.lower() in q:
            return j
    return None


def detect_unlawful_intent(question: str) -> bool:
    q = question.lower()
    return any(re.search(p, q) for p in UNLAWFUL_PATTERNS)


def is_in_domain(question: str) -> bool:
    q = question.lower()
    return any(h.lower() in q for h in _CONTEXT_HINTS)


def pre_check(question: str) -> tuple[str, str] | None:
    """Return (refusal_reason, refusal_text) or None if the question may proceed.

    A foreign jurisdiction mention short-circuits immediately. Retrieval would
    happily find a semantically adjacent Saudi article and the model would
    answer from it -- which is exactly the failure this guard exists to stop.
    """
    if detect_jurisdiction(question):
        return "out_of_scope", _refusal_out_of_scope_ar
    if detect_unlawful_intent(question):
        return "unlawful_intent", _refusal_unlawful_ar
    return None


def no_evidence_refusal() -> tuple[str, str]:
    return "no_evidence", _refusal_no_evidence_ar
