"""PII redaction at the ingestion boundary.

Runs BEFORE storage and before any third-party call. Heuristic by design --
a regex cannot find every Saudi name -- so the contract carries a
``redaction_report`` and the UI states coverage limits instead of pretending
to be complete.

If you need real name detection, add a model, and add it *before* this module's
output is used, not after.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Saudi national ID / Iqama: 10 digits, starts with 1 (citizen) or 2 (resident).
NATIONAL_ID = re.compile(r"\b[12]\d{9}\b")
# IBAN: SA + 2 check digits + 20 alphanumerics.
IBAN = re.compile(r"\bSA\d{2}[A-Z0-9]{20}\b", re.IGNORECASE)
PHONE = re.compile(r"(?:\+966|00966|0)?\s?5\d{8}\b")
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b")
# Money amounts (SAR) -- less sensitive but used to avoid leaking salary data.
MONEY = re.compile(
    r"\b\d[\d,]{2,}(?:\.\d{1,2})?\s*(?:ر\.?\s?س|ريال|SAR|SR)\b", re.IGNORECASE
)
HONORIFIC_NAME = re.compile(
    r"\b(?:السيد|السيدة|الأستاذ|الاستاذ|المهندس|الدكتور|الشيخ|الأستاذة|الأنسة)"
    r"(?:\s+[\u0600-\u06FF]{2,}){1,3}"
)

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("IBAN", IBAN),
    ("NATIONAL_ID", NATIONAL_ID),
    ("PHONE", PHONE),
    ("EMAIL", EMAIL),
    ("MONEY", MONEY),
    ("NAME", HONORIFIC_NAME),
]


@dataclass
class RedactionReport:
    counts: dict[str, int]
    total: int

    @property
    def clean(self) -> bool:
        return self.total == 0


def redact(text: str) -> tuple[str, RedactionReport]:
    """Return (redacted_text, report). Stable tokens so quotes stay matchable."""
    counts: dict[str, int] = {}
    counters: dict[str, int] = {}
    for label, pattern in PATTERNS:
        def _sub(m: re.Match[str], _label: str = label) -> str:
            counters[_label] = counters.get(_label, 0) + 1
            counts[_label] = counts.get(_label, 0) + 1
            return f"[{_label}_{counters[_label]}]"

        text = pattern.sub(_sub, text)
    return text, RedactionReport(counts=counts, total=sum(counts.values()))


def is_safe_to_send(text: str) -> bool:
    """Cheap pre-flight gate: refuses to send text containing obvious identifiers."""
    return not any(p.search(text) for _, p in PATTERNS)
