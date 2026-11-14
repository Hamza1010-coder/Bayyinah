"""The pipeline. Deterministic stages, no agent.

    guardrail -> retrieve -> evidence gate -> generate -> verify -> repair
              -> calculate -> assemble

Every stage is measurable on its own, which is what makes the eval harness
possible. An agent loop here would trade that for nothing.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from .. import __version__
from ..calc.eos import end_of_service
from ..guardrails.refusal import no_evidence_refusal, pre_check
from ..retrieval.expand import expand_query, explain as explain_expansions
from ..schemas import Answer, Calculation, Citation
from ..text.normalize import content_tokens, unify_digits
from .llm import LLM, get_default_llm
from .verifier import has_hard_failure, summarize, verify

DISCLAIMER_AR = (
    "هذه معلومات عامة وليست استشارة قانونية. للحالات النزاعية أو الخاصة "
    "يرجى مراجعة محامٍ مرخّص في المملكة."
)

RISK_TERMS = {
    "termination": ["فصل", "إنهاء", "انهاء", "مفصول", "termination"],
    "resignation": ["استقال", "استقالة", "resignation"],
    "financial_liability": ["مكافأة", "تعويض", "مستحقات", "راتب", "أجر", "اجر"],
    "dispute": ["نزاع", "محكمة", "قضية", "شكوى", "هيئة"],
}

NUM = r"[0-9\u0660-\u0669\u06F0-\u06F9][0-9\u0660-\u0669\u06F0-\u06F9,\.]*"
YEARS_RE = re.compile(r"(" + NUM + r")\s*(?:سنوات|سنة|سنه|عام|أعوام|اعوام)")
SALARY_RE = re.compile(r"(?:راتب|أجر|الراتب|الأجر|salary|wage)[^\d\u0660-\u0669]{0,20}(" + NUM + r")", re.IGNORECASE)
SALARY_SUFFIX_RE = re.compile(r"(" + NUM + r")\s*(?:ر\.?\s?س|ريال|SAR|SR)", re.IGNORECASE)


@dataclass
class PipelineConfig:
    k: int = 5
    min_evidence: float = 0.25
    # A match on a term that appears in most articles ("خدمة", "عامل") is not
    # evidence. Require at least one *distinctive* term (low document
    # frequency) before answering. Without this, stemming turns
    # "الخدمات" into "خدم" and a VAT question gets answered with labour law.
    min_term_idf: float = 0.85
    max_repair_passes: int = 1
    require_citation: bool = True


@dataclass
class Trace:
    stages: list[dict] = field(default_factory=list)

    def add(self, stage: str, **data) -> None:
        self.stages.append({"stage": stage, **data})


def _to_float(raw: str) -> float | None:
    cleaned = unify_digits(raw).replace(",", "").replace("،", "").strip(".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _evidence_strength(question: str, chunk) -> float:
    """Share of the question's *content* terms present in the chunk.

    Stopwords are excluded: 'ما هي X في Y' must not score 2/9 against an
    unrelated article just because it contains 'في'.
    """
    q = set(content_tokens(question))
    if not q:
        return 0.0
    c = set(content_tokens(chunk.text_norm))
    return len(q & c) / len(q)


def _has_distinctive_match(question: str, chunks: list, corpus, threshold: float) -> bool:
    q = set(content_tokens(question))
    for chunk in chunks:
        for term in q & set(content_tokens(chunk.text_norm)):
            if corpus.idf(term) >= threshold:
                return True
    return False


def maybe_calculate(question: str) -> Calculation | None:
    """Detect an end-of-service question and compute it deterministically."""
    q = question
    has_eos_intent = any(
        term in q for term in ("مكافأة", "نهاية الخدمة", "نهايه الخدمه", "مستحقات")
    )
    if not has_eos_intent:
        return None

    years_match = YEARS_RE.search(q)
    if not years_match:
        return None
    years = _to_float(years_match.group(1))
    if years is None:
        return None

    salary = None
    if m := SALARY_RE.search(q):
        salary = _to_float(m.group(1))
    if salary is None and (m := SALARY_SUFFIX_RE.search(q)):
        salary = _to_float(m.group(1))
    if salary is None:
        return None

    reason = "termination"
    if any(t in q for t in ("استقل", "استقالة", "استقاله", "أستقيل")):
        reason = "resignation"

    return end_of_service(salary, years, reason)


class CompliancePipeline:
    def __init__(self, store, llm: LLM | None = None, config: PipelineConfig | None = None):
        self.store = store
        self.llm = llm or get_default_llm()
        self.config = config or PipelineConfig()

    def answer(self, question: str) -> Answer:
        trace = Trace()
        started = time.perf_counter()
        answer = Answer(question=question)

        blocked = pre_check(question)
        if blocked:
            reason, text = blocked
            trace.add("guardrail", refusal=reason)
            answer.refusal = text
            answer.refusal_reason = reason
            answer.confidence = "high"
            answer.meta = {"trace": trace.stages, "version": __version__}
            return answer

        query = expand_query(question)
        hits = self.store.search(query, k=self.config.k)
        trace.add(
            "retrieve",
            n=len(hits),
            articles=[h[0].article_no for h in hits],
            expansions=explain_expansions(question),
        )

        weak = (
            not hits
            or max(_evidence_strength(query, h[0]) for h in hits) < self.config.min_evidence
            or not _has_distinctive_match(
                query,
                [h[0] for h in hits],
                self.store,
                self.config.min_term_idf,
            )
        )
        if weak:
            trace.add("gate", result="no_evidence")
            reason, text = no_evidence_refusal()
            answer.refusal = text
            answer.refusal_reason = reason
            answer.confidence = "high"
            answer.requires_human_review = True
            answer.meta = {"trace": trace.stages, "version": __version__}
            return answer

        chunks = [h[0] for h in hits]
        calculation = maybe_calculate(question)
        if calculation:
            trace.add("calculate", kind=calculation.kind, result=calculation.result)

        raw = self._generate_with_repair(question, chunks, trace)
        self._assemble(answer, raw, chunks, trace)
        answer.calculations = [calculation] if calculation else []
        answer.risk_flags = self._risk_flags(question)
        answer.requires_human_review = (
            answer.requires_human_review
            or "dispute" in answer.risk_flags
            or answer.confidence == "low"
        )
        answer.meta = {
            "trace": trace.stages,
            "version": __version__,
            "llm": self.llm.name,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "synthetic_corpus": any(c.synthetic for c in chunks),
        }
        return answer

    # -- internals --------------------------------------------------------
    def _generate_with_repair(self, question: str, chunks: list, trace: Trace) -> dict:
        raw = self.llm.generate(question, chunks)
        for attempt in range(self.config.max_repair_passes + 1):
            probe = Answer(question=question)
            self._assemble(probe, raw, chunks, Trace(), collect_meta=False)
            problems = verify(probe, self.store)
            trace.add("verify", attempt=attempt, hard=has_hard_failure(problems),
                      problems=[p.kind for p in problems])
            if not has_hard_failure(problems) or attempt == self.config.max_repair_passes:
                raw["_verification"] = [p.to_dict() for p in problems]
                return raw
            raw = self.llm.generate(question, chunks, problems=summarize(problems))
        return raw

    def _assemble(self, answer: Answer, raw: dict, chunks: list, trace: Trace, *,
                  collect_meta: bool = True) -> None:
        answer.answer_ar = str(raw.get("answer") or raw.get("answer_ar") or "").strip()
        answer.confidence = raw.get("confidence", "low")
        answer.refusal = raw.get("refusal")
        answer.risk_flags = list(raw.get("risk_flags") or [])

        citations: list[Citation] = []
        for c in raw.get("citations") or []:
            citations.append(
                Citation(
                    doc_id=str(c.get("doc_id") or ""),
                    article_no=str(c.get("article_no") or ""),
                    quote=str(c.get("quote") or ""),
                    page=int(c.get("page") or 0),
                    url=str(c.get("url") or ""),
                )
            )
        # Fill display metadata from the corpus.
        for cit in citations:
            src = self.store.get_article(cit.doc_id, cit.article_no) if cit.doc_id else None
            if src is None:
                for chunk in chunks:
                    if str(chunk.article_no) == cit.article_no:
                        src = chunk
                        break
            if src is not None:
                cit.doc_id = cit.doc_id or src.doc_id
                cit.page = cit.page or src.page
                cit.url = cit.url or src.url
        answer.citations = citations
        answer.verification = verify(answer, self.store)

        if has_hard_failure(answer.verification):
            # Strip the citations we could not prove, keep the ones we could.
            bad = {p.citation.get("article_no") for p in answer.verification
                   if p.severity == "hard" and p.citation}
            answer.citations = [c for c in answer.citations if c.article_no not in bad]
            answer.confidence = "low"
            answer.requires_human_review = True
            trace.add("downgrade", dropped=len(bad))
            if not answer.citations:
                answer.answer_ar = (
                    "تعذّر التحقق من الاستشهادات، لذا لن أقدّم صياغة. "
                    "هذه المصادر ذات الصلة للمراجعة اليدوية."
                )
                answer.refusal = "unverified"
                answer.refusal_reason = "unverified"

        if collect_meta:
            trace.add("assemble", citations=len(answer.citations),
                      confidence=answer.confidence)

    @staticmethod
    def _risk_flags(question: str) -> list[str]:
        flags = []
        for flag, terms in RISK_TERMS.items():
            if any(t in question for t in terms):
                flags.append(flag)
        return flags
