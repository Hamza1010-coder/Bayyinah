"""Typed contracts for everything that crosses a boundary.

Plain dataclasses, no pydantic: the core stays dependency-free so the demo runs
on a bare interpreter. The JSON shape here IS the API contract and the thing
the verifier enforces.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Literal

Confidence = Literal["high", "medium", "low"]
Verdict = Literal["compliant", "risky", "non_compliant", "not_covered"]
Severity = Literal["high", "medium", "low"]


@dataclass
class Citation:
    doc_id: str
    article_no: str
    quote: str
    page: int = 0
    url: str = ""
    title: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Calculation:
    kind: str
    inputs: dict
    result: float
    unit: str = "SAR"
    formula_ref: str = ""
    trace: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class VerificationProblem:
    kind: str                      # article_not_found | quote_not_verbatim | quote_not_supporting
    severity: str                  # hard | soft
    detail: str
    citation: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Answer:
    question: str
    answer_ar: str = ""
    answer_en: str = ""
    citations: list[Citation] = field(default_factory=list)
    calculations: list[Calculation] = field(default_factory=list)
    confidence: Confidence = "low"
    refusal: str | None = None
    refusal_reason: str | None = None   # out_of_scope | no_evidence | unlawful_intent
    risk_flags: list[str] = field(default_factory=list)
    requires_human_review: bool = False
    disclaimer_required: bool = True
    verification: list[VerificationProblem] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["citations"] = [c.to_dict() for c in self.citations]
        d["calculations"] = [c.to_dict() for c in self.calculations]
        d["verification"] = [p.to_dict() for p in self.verification]
        return d

    @property
    def grounded(self) -> bool:
        return bool(self.citations) and not any(p.severity == "hard" for p in self.verification)


@dataclass
class Finding:
    clause_id: str
    clause_text: str
    verdict: Verdict
    severity: Severity
    rationale: str = ""
    suggested_redline: str = ""
    citation: Citation | None = None
    confidence: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["citation"] = self.citation.to_dict() if self.citation else None
        return d


@dataclass
class XRayReport:
    document_id: str
    filename: str
    findings: list[Finding] = field(default_factory=list)
    redaction: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        out = {v: 0 for v in ("non_compliant", "risky", "compliant", "not_covered")}
        for f in self.findings:
            out[f.verdict] = out.get(f.verdict, 0) + 1
        return out

    def to_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "filename": self.filename,
            "counts": self.counts(),
            "findings": [f.to_dict() for f in self.findings],
            "redaction": self.redaction,
            "notes": self.notes,
        }


@dataclass
class GoldItem:
    id: str
    question: str
    gold_articles: list[str]
    answerable: bool = True
    lang: str = "ar"
    category: str = ""
    gold_answer: str = ""
    difficulty: str = "medium"
    must_refuse: bool = False
    notes: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "GoldItem":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})
