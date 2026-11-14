"""Deterministic calculators. The LLM never does arithmetic here.

Every number a user might act on (money, days) comes out of a pure function
that has unit tests. The model's only job is to restate the result.

Rules encoded are those commonly applied under Articles 84-85 of the Saudi
Labor Law (base award: half a month per year for the first five years, one
month per year thereafter; resignation fractions by length of service).

These are implementation choices, not legal advice. A Saudi HR practitioner
must sign off before this ships to real users -- see docs/pdpl-mapping.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..schemas import Calculation

# Resignation entitlement fractions (Article 85).
RESIGNATION_BANDS: list[tuple[float, float, str]] = [
    (0.0, 2.0, "0"),
    (2.0, 5.0, "1/3"),
    (5.0, 10.0, "2/3"),
    (10.0, float("inf"), "1"),
]


def base_award(salary: float, years: float) -> float:
    """Article 84: half-month wage per year for the first 5 years, then one month."""
    if salary <= 0 or years <= 0:
        return 0.0
    first = min(years, 5.0)
    rest = max(years - 5.0, 0.0)
    return salary * (0.5 * first + 1.0 * rest)


def resignation_fraction(years: float) -> tuple[float, str]:
    for lo, hi, label in RESIGNATION_BANDS:
        if lo <= years < hi or (hi == float("inf") and years >= lo):
            return {"0": 0.0, "1/3": 1 / 3, "2/3": 2 / 3, "1": 1.0}[label], label
    return 0.0, "0"


def end_of_service(
    salary: float,
    years: float,
    reason: str = "termination",
    *,
    full_award_override: bool = False,
) -> Calculation:
    """Compute the end-of-service award.

    reason: "termination" (employer-initiated, not for cause) -> full award
            "resignation"                                 -> Article 85 band
            "article_80"  (dismissal for cause under Art. 80) -> no award
    """
    reason = reason.strip().lower()
    base = base_award(salary, years)
    trace = [
        f"المكافأة الأساسية (المادة ٨٤): {base:,.2f} ر.س",
    ]

    if reason in {"resignation", "استقالة"}:
        if full_award_override:
            fraction, label = 1.0, "1"
        else:
            fraction, label = resignation_fraction(years)
        trace.append(f"نسبة الاستحقاق عند الاستقالة (المادة ٨٥): {label}")
        award = base * fraction
        formula = "art_84+art_85"
    elif reason in {"article_80", "art_80", "فصل_80"}:
        trace.append("الفصل وفق المادة ٨٠: لا يستحق العامل مكافأة.")
        award, formula = 0.0, "art_80"
    else:
        trace.append("إنهاء من صاحب العمل دون سبب مشروع: المكافأة كاملة.")
        award, formula = base, "art_84"

    return Calculation(
        kind="end_of_service",
        inputs={"salary": salary, "years": years, "reason": reason},
        result=round(award, 2),
        unit="SAR",
        formula_ref=formula,
        trace=trace,
    )


def notice_period_days(years: float) -> int:
    """Statutory notice: 30 days, 60 for monthly-paid staff after 5 years.

    Kept as a single simple rule with a TODO rather than a confident guess.
    """
    return 60 if years >= 5 else 30
