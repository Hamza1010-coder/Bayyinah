"""Application services.

The API layer owns HTTP; this layer owns behaviour. Everything that should be
logged, costed, or audited happens here so the same guarantees apply whether a
request comes from the web UI, the CLI, or the eval harness.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass

from .config import Settings
from .contracts.analyzer import AnalysisResult, ContractAnalyzer
from .db import Database, utcnow
from .generation.llm import LLM, get_default_llm
from .generation.pipeline import CompliancePipeline, PipelineConfig
from .schemas import Answer

# USD per 1M tokens: (input, output). Rough, for budgeting not billing.
PRICES = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "claude-3-5-haiku": (0.80, 4.00),
    "default": (0.50, 1.50),
}


def estimate_tokens(text: str) -> int:
    # Arabic averages ~3.2 chars/token on modern tokenizers; 3.5 is a safe floor.
    return max(1, int(len(text) / 3.5))


def estimate_cost(model: str, prompt_chars: int, answer_chars: int) -> float:
    price_in, price_out = PRICES.get(model, PRICES["default"])
    return round(
        (estimate_tokens("x" * prompt_chars) / 1_000_000) * price_in
        + (estimate_tokens("x" * answer_chars) / 1_000_000) * price_out,
        6,
    )


@dataclass
class AnswerResult:
    answer: Answer
    query_id: int
    latency_ms: float
    cost_usd: float
    model: str

    def to_dict(self) -> dict:
        return {
            "answer": self.answer.to_dict(),
            "query_id": self.query_id,
            "latency_ms": self.latency_ms,
            "cost_usd": self.cost_usd,
            "model": self.model,
        }


class AnswerService:
    def __init__(self, corpus, settings: Settings, llm: LLM | None = None, db: Database | None = None):
        self.corpus = corpus
        self.settings = settings
        self.db = db
        self.llm = llm or get_default_llm()
        self.pipeline = CompliancePipeline(
            corpus,
            llm=self.llm,
            config=PipelineConfig(
                k=settings.top_k,
                min_evidence=settings.min_evidence,
                min_term_idf=settings.min_term_idf,
            ),
        )

    def ask(self, question: str, actor: str = "anonymous") -> AnswerResult:
        started = time.perf_counter()
        answer = self.pipeline.answer(question)
        latency_ms = round((time.perf_counter() - started) * 1000, 1)

        prompt_chars = len(question) + sum(len(c.quote) for c in answer.citations) + 600
        answer_chars = len(answer.answer_ar)
        cost = estimate_cost(self.llm.name, prompt_chars, answer_chars)

        query_id = 0
        if self.db is not None:
            query_id = self.db.log_query(
                question=question,
                answer_json=json.dumps(answer.to_dict(), ensure_ascii=False),
                refusal_reason=answer.refusal_reason,
                confidence=answer.confidence,
                latency_ms=latency_ms,
                cost_usd=cost,
                model=self.llm.name,
                verification_ok=answer.grounded or bool(answer.refusal),
                n_citations=len(answer.citations),
                actor=actor,
            )
        return AnswerResult(
            answer=answer, query_id=query_id, latency_ms=latency_ms, cost_usd=cost, model=self.llm.name
        )


class ContractService:
    def __init__(self, corpus, db: Database, analyzer: ContractAnalyzer | None = None):
        self.corpus = corpus
        self.db = db
        self.analyzer = analyzer or ContractAnalyzer(corpus)

    def analyze(self, text: str, filename: str = "contract.txt", actor: str = "anonymous") -> tuple[str, AnalysisResult]:
        result = self.analyzer.analyze(text, filename=filename)
        contract_id = str(uuid.uuid4())
        self.db.save_contract(
            id=contract_id,
            ts=utcnow(),
            filename=filename,
            report=result.report.to_dict(),
            counts=result.report.counts(),
            redaction=result.redaction,
            actor=actor,
        )
        self.db.audit("contract_analyzed", {"contract_id": contract_id, "file": filename,
                                            "counts": result.report.counts()}, actor=actor)
        return contract_id, result

    def get(self, contract_id: str) -> dict | None:
        row = self.db.contract(contract_id)
        if row is None:
            return None
        return {
            "id": row["id"],
            "ts": row["ts"],
            "filename": row["filename"],
            "report": json.loads(row["report_json"]),
            "counts": json.loads(row["counts_json"]),
            "redaction": json.loads(row["redaction_json"] or "{}"),
        }

    def report_markdown(self, contract_id: str) -> str | None:
        from .contracts.report import to_markdown

        payload = self.get(contract_id)
        if payload is None:
            return None
        report = _report_from_dict(payload["report"])
        return to_markdown(report)


def _report_from_dict(data: dict):
    """Rebuild an XRayReport from stored JSON (findings carry citations)."""
    from .schemas import Citation, Finding, XRayReport

    report = XRayReport(
        document_id=data.get("document_id", ""),
        filename=data.get("filename", ""),
        notes=list(data.get("notes") or []),
        redaction=dict(data.get("redaction") or {}),
    )
    for item in data.get("findings") or []:
        cit = item.get("citation")
        report.findings.append(
            Finding(
                clause_id=item.get("clause_id", ""),
                clause_text=item.get("clause_text", ""),
                verdict=item.get("verdict", "not_covered"),
                severity=item.get("severity", "low"),
                rationale=item.get("rationale", ""),
                suggested_redline=item.get("suggested_redline", ""),
                citation=Citation(**cit) if cit else None,
                confidence=float(item.get("confidence") or 0.0),
            )
        )
    return report


def stats(db: Database) -> dict:
    return {
        "chunks": db.count_chunks(),
        "documents": len(db.documents()),
        "queries": db.query_stats(),
        "feedback": db.feedback_stats(),
    }
