"""Contract X-Ray: clause segmentation + rule-based triage.

This is the deterministic layer: rules over clause text, each rule bound to an
article, each finding carrying the article it violates. It catches the
high-frequency, high-severity mistakes (probation too long, waiver of
end-of-service pay, excess hours, sub-minimum leave) without an LLM in the loop.

The LLM layer lives in `analyzer.py` and runs *after* this, subject to the same
citation verification. Rules first: they are free, instant, testable, and cannot
hallucinate.
"""

from __future__ import annotations

import re
import uuid

from ..schemas import Citation, Finding, XRayReport

CLAUSE_START = re.compile(
    r"(?:^|\n)\s*(?:البند|بند|المادة|الماده)\s*[\(\[]?\s*([0-9\u0660-\u0669]{1,2})\s*[\)\]]?[\s:\-–]*",
)

HOURS = re.compile(r"([0-9\u0660-\u0669]{2})\s*(?:ساعة|ساعات)")

# Contracts write durations in words as often as in digits: "ستة أشهر",
# "أربعة أشهر". A detector that only reads digits misses the most common
# phrasing in real Arabic contracts.
NUM_WORDS = {
    "واحد": 1, "واحدة": 1, "اثنان": 2, "اثنين": 2, "اثنتان": 2,
    "ثلاثة": 3, "ثلاث": 3, "أربعة": 4, "اربعة": 4, "خمسة": 5, "خمس": 5,
    "ستة": 6, "ست": 6, "سبعة": 7, "سبع": 7, "ثمانية": 8, "ثماني": 8,
    "تسعة": 9, "تسع": 9, "عشرة": 10, "عشر": 10, "إحدى": 1, "احدى": 1,
}

WORD_ALT = "|".join(sorted(NUM_WORDS, key=len, reverse=True))
NUMBER = r"(?:[0-9\u0660-\u0669]{1,3}|" + WORD_ALT + r")"

PROBATION_WINDOW = re.compile(NUMBER + r"\s*(?:\(\s*[0-9]{1,3}\s*\)\s*)?(?:يوماً|يوما|يوم|شهر|أشهر|اشهر)")
LEAVE_DAYS = re.compile(NUMBER + r"\s*(?:\(\s*[0-9]{1,2}\s*\)\s*)?(?:يوماً|يوما|يوم)")


def _num(raw: str) -> int | None:
    raw = raw.strip()
    if raw in NUM_WORDS:
        return NUM_WORDS[raw]
    digits = raw.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    try:
        return int(digits)
    except ValueError:
        return None


def _duration_days(text: str) -> int | None:
    """'ستة أشهر' -> 180, '٩٠ يوماً' -> 90."""
    match = PROBATION_WINDOW.search(text)
    if not match:
        return None
    raw = match.group(0)
    number = NUMBER_MATCH.search(raw)
    if not number:
        return None
    value = _num(number.group(0))
    if value is None:
        return None
    return value * 30 if ("شهر" in raw or "أشهر" in raw or "اشهر" in raw) else value


NUMBER_MATCH = re.compile(NUMBER)


def segment_clauses(text: str) -> list[tuple[str, str]]:
    """Return [(clause_id, clause_text)]. Falls back to paragraphs."""
    marks = list(CLAUSE_START.finditer(text))
    if len(marks) < 2:
        paras = [p.strip() for p in re.split(r"\n{2,}", text) if len(p.strip()) > 20]
        return [(f"c-{i:03d}", p) for i, p in enumerate(paras, start=1)]

    out: list[tuple[str, str]] = []
    for i, match in enumerate(marks):
        stop = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[match.end() : stop].strip()
        if body:
            out.append((f"c-{i + 1:03d}", body))
    return out


def _find_article(corpus, article_no: str):
    """Resolve an article across the whole corpus (multiple documents possible)."""
    if corpus is None:
        return None
    for chunk in corpus.chunks:
        if str(chunk.article_no) == str(article_no):
            return chunk
    return None


def _finding(clause_id: str, clause: str, verdict, severity, article: str,
             rationale: str, redline: str, confidence: float, corpus) -> Finding:
    source = _find_article(corpus, article)
    citation = None
    if source is not None:
        citation = Citation(
            doc_id=source.doc_id,
            article_no=article,
            quote=source.text_display[:220],
            page=source.page,
            url=source.url,
        )
    return Finding(
        clause_id=clause_id,
        clause_text=clause,
        verdict=verdict,
        severity=severity,
        rationale=rationale,
        suggested_redline=redline,
        citation=citation,
        confidence=confidence,
    )


def analyze(text: str, corpus, *, filename: str = "contract.txt") -> XRayReport:
    report = XRayReport(document_id=str(uuid.uuid4()), filename=filename)

    if not corpus or not len(corpus):
        report.notes.append("لا توجد قاعدة نظامية محمّلة — التحليل محدود.")
        return report

    for clause_id, clause in segment_clauses(text):
        lowered = clause.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))

        # -- probation -----------------------------------------------------
        if "تجربة" in clause or "التجربة" in clause:
            window = _duration_days(lowered)
            if window and window > 90:
                report.findings.append(
                    _finding(
                        clause_id, clause, "non_compliant", "high", "53",
                        f"فترة التجربة المذكورة ({window} يوماً) تتجاوز الحد النظامي ٩٠ يوماً.",
                        "تُستبدل بـ: «تكون فترة التجربة تسعين (٩٠) يوماً غير قابلة للتمديد».",
                        0.9, corpus,
                    )
                )
                continue

        # -- waiver of end-of-service --------------------------------------
        if re.search(r"(?:تنازل|إسقاط|اسقاط|يتنازل)", clause) and re.search(
            r"(?:مكافأة|نهاية الخدمة|مستحقات)", clause
        ):
            report.findings.append(
                _finding(
                    clause_id, clause, "non_compliant", "high", "84",
                    "لا يجوز الاتفاق على إسقاط حق العامل في مكافأة نهاية الخدمة؛ الشرط باطل.",
                    "يُحذف البند بالكامل.",
                    0.9, corpus,
                )
            )
            continue

        # -- working hours --------------------------------------------------
        if match := HOURS.search(lowered):
            hours = _num(match.group(1))
            if hours and hours > 48 and ("أسبوع" in clause or "اسبوع" in clause):
                report.findings.append(
                    _finding(
                        clause_id, clause, "non_compliant", "high", "98",
                        f"ساعات العمل الأسبوعية ({hours}) تتجاوز الحد النظامي ٤٨ ساعة.",
                        "تُعدل إلى ٤٨ ساعة أسبوعياً كحد أقصى.",
                        0.85, corpus,
                    )
                )
                continue
            if hours and hours > 8 and "يوم" in clause:
                report.findings.append(
                    _finding(
                        clause_id, clause, "risky", "medium", "98",
                        f"ساعات العمل اليومية ({hours}) تتجاوز الحد النظامي ٨ ساعات.",
                        "تُعدل إلى ٨ ساعات يومياً مع احتساب العمل الإضافي.",
                        0.8, corpus,
                    )
                )
                continue

        # -- annual leave ----------------------------------------------------
        if "إجازة" in clause or "اجازة" in clause:
            match = LEAVE_DAYS.search(lowered)
            days = None
            if match:
                number = NUMBER_MATCH.search(match.group(0))
                days = _num(number.group(0)) if number else None
            if days and days < 21:
                report.findings.append(
                    _finding(
                        clause_id, clause, "non_compliant", "medium", "109",
                        f"الإجازة السنوية ({days} يوماً) أقل من الحد النظامي ٢١ يوماً.",
                        "تُعدل إلى ٢١ يوماً على الأقل (٣٠ يوماً بعد خمس سنوات خدمة).",
                        0.85, corpus,
                    )
                )
                continue

        # -- termination without notice --------------------------------------
        if re.search(r"(?:فصل|إنهاء|انهاء)", clause) and re.search(
            r"(?:دون|بدون)\s*(?:إشعار|اشعار)", clause
        ):
            report.findings.append(
                _finding(
                    clause_id, clause, "risky", "medium", "60",
                    "الإنهاء دون إشعار قد يكون تعسفياً ما لم يثبت سبب مشروع وفق المادة ٨٠.",
                    "يُضاف: «لا يجوز الإنهاء إلا بعد إشعار كتابي مدته ٣٠ يوماً أو لسبب مشروع».",
                    0.7, corpus,
                )
            )
            continue

        report.findings.append(
            Finding(
                clause_id=clause_id,
                clause_text=clause,
                verdict="not_covered",
                severity="low",
                rationale="لا تنطبق عليه قاعدة آلية — يحتاج مراجعة يدوية.",
                confidence=0.3,
            )
        )

    return report
