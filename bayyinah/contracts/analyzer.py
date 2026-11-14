"""Contract analysis orchestration.

Two layers, in this order:

1. **Deterministic rules** (`xray.py`) -- free, instant, testable, no hallucination.
2. **LLM pass** -- only for clauses the rules did not cover, and only accepted if
   the returned quote is verifiably present in the cited article. Same contract
   as the Q&A path: no verified quote, no finding.

The rules stay first on purpose. If the model is down, slow, or wrong, the
product still catches the four violations that matter most.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..schemas import Citation, Finding, XRayReport
from ..text.normalize import contains_normalized
from .xray import analyze as rule_analyze

MAX_LLM_CLAUSES = 15
MIN_CLAUSE_CHARS = 40


@dataclass
class AnalysisResult:
    report: XRayReport
    redaction: dict
    coverage: dict

    def to_dict(self) -> dict:
        return {
            "report": self.report.to_dict(),
            "redaction": self.redaction,
            "coverage": self.coverage,
        }


class ContractAnalyzer:
    def __init__(self, corpus, llm=None):
        self.corpus = corpus
        self.llm = llm

    def analyze(self, text: str, filename: str = "contract.txt") -> AnalysisResult:
        from ..text.pii import redact

        clean, redaction = redact(text)
        report = rule_analyze(clean, self.corpus, filename=filename)
        report.redaction = redaction.counts

        llm_used = 0
        if self.llm is not None and hasattr(self.llm, "contract_verdict"):
            llm_used = self._llm_pass(report)

        covered = sum(1 for f in report.findings if f.verdict != "not_covered")
        coverage = {
            "clauses": len(report.findings),
            "covered_by_rules": covered - llm_used,
            "covered_by_llm": llm_used,
            "uncovered": len(report.findings) - covered,
        }
        report.notes.append(
            f"قواعد آلية غطّت {covered - llm_used} من {len(report.findings)} بنداً"
            + (f"، ونموذج لغوي غطّى {llm_used}" if llm_used else "")
            + "."
        )
        return AnalysisResult(report=report, redaction=redaction.counts, coverage=coverage)

    # -- internals --------------------------------------------------------
    def _llm_pass(self, report: XRayReport) -> int:
        used = 0
        candidates = [f for f in report.findings if f.verdict == "not_covered"]
        for finding in candidates[:MAX_LLM_CLAUSES]:
            if len(finding.clause_text) < MIN_CLAUSE_CHARS:
                continue
            chunks = [c for c, _ in self.corpus.search(finding.clause_text, k=4)]
            if not chunks:
                continue
            verdict = self.llm.contract_verdict(finding.clause_text, chunks)
            if not verdict:
                continue
            article_no = str(verdict.get("article_no") or "").strip()
            source = next((c for c in chunks if str(c.article_no) == article_no), None)
            if source is None:
                continue  # cited an article that was not even retrieved

            quote = str(verdict.get("quote") or "").strip()
            if not quote or not contains_normalized(source.text_display, quote):
                # The model paraphrased. Do not let it become a finding.
                quote = source.text_display[:200]

            verdict_label = str(verdict.get("verdict") or "not_covered")
            if verdict_label not in {"compliant", "risky", "non_compliant", "not_covered"}:
                continue

            finding.verdict = verdict_label  # type: ignore[assignment]
            finding.severity = str(verdict.get("severity") or "low")  # type: ignore[assignment]
            finding.rationale = str(verdict.get("rationale") or finding.rationale)
            finding.suggested_redline = str(verdict.get("suggested_redline") or "")
            finding.citation = Citation(
                doc_id=source.doc_id,
                article_no=source.article_no,
                quote=quote,
                page=source.page,
                url=source.url,
            )
            try:
                finding.confidence = float(verdict.get("confidence") or 0.5)
            except (TypeError, ValueError):
                finding.confidence = 0.5
            used += 1
        return used


def analyze_file(analyzer: ContractAnalyzer, path: str) -> AnalysisResult:
    from ..ingest.loaders import load

    loaded = load(path)
    result = analyzer.analyze(loaded.text, filename=loaded.filename)
    result.report.notes.extend(loaded.warnings)
    return result
