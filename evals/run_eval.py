"""Eval harness.

    python evals/run_eval.py                 # QA + contract suites
    python evals/run_eval.py --suite qa --fail-on-gate

Reads the live SQLite corpus (the same one the server uses), so the numbers
describe the product rather than a fixture nobody ships.

Reports go to evals/reports/ and are meant to be committed: the diff between two
reports is the evidence that the system improved against a measurement.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from bayyinah.contracts.xray import analyze as rule_analyze  # noqa: E402
from bayyinah.db import Database  # noqa: E402
from bayyinah.generation.llm import get_default_llm  # noqa: E402
from bayyinah.generation.pipeline import CompliancePipeline, PipelineConfig  # noqa: E402
from bayyinah.retrieval.corpus import SqliteCorpus  # noqa: E402
from bayyinah.schemas import GoldItem  # noqa: E402
from evals import metrics  # noqa: E402

QA_GATES = {
    "recall_at_5": (0.80, ">="),
    "mrr": (0.60, ">="),
    "refusal_accuracy": (0.90, ">="),
    "citation_validity": (1.00, ">="),
    "false_refusal_rate": (0.10, "<="),
}

CONTRACT_GATES = {
    "violation_precision": (0.80, ">="),
    "violation_recall": (0.80, ">="),
    "citation_rate": (0.95, ">="),
}


def load_jsonl(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


# ---------------------------------------------------------------------------
# QA suite
# ---------------------------------------------------------------------------
def run_qa(store, items: list[GoldItem], k: int, llm) -> dict:
    pipeline = CompliancePipeline(
        store, llm=llm, config=PipelineConfig(k=k, min_evidence=0.25, min_term_idf=0.85)
    )
    rows = []
    for item in items:
        started = time.perf_counter()
        answer = pipeline.answer(item.question)
        latency = (time.perf_counter() - started) * 1000

        hits = [c.article_no for c, _ in store.search(item.question, k=k)]
        cited = [c.article_no for c in answer.citations]
        hard_fail = any(p.severity == "hard" for p in answer.verification)

        rows.append(
            {
                "id": item.id,
                "answerable": item.answerable,
                "must_refuse": item.must_refuse,
                "refused": bool(answer.refusal),
                "refusal_reason": answer.refusal_reason,
                "retrieved": hits,
                "cited": cited,
                "recall_at_k": metrics.recall_at_k(item.gold_articles, hits, k) if item.answerable else None,
                "reciprocal_rank": metrics.mrr(item.gold_articles, hits) if item.answerable else None,
                "citation_precision": metrics.citation_precision(cited, item.gold_articles)
                if item.answerable and cited
                else None,
                "citation_valid": (not hard_fail) if answer.citations else None,
                "grounded": bool(answer.citations),
                "confidence": answer.confidence,
                "latency_ms": round(latency, 1),
                "calculations": [c.result for c in answer.calculations],
            }
        )

    answerable = [r for r in rows if r["answerable"]]
    refusable = [r for r in rows if r["must_refuse"]]
    summary = {
        "recall_at_5": metrics.mean((r["recall_at_k"] or 0.0) for r in answerable),
        "mrr": metrics.mean((r["reciprocal_rank"] or 0.0) for r in answerable),
        "citation_precision": metrics.mean(
            (r["citation_precision"] or 0.0) for r in answerable if r["citation_precision"] is not None
        ),
        "citation_validity": metrics.rate(r["citation_valid"] for r in rows if r["citation_valid"] is not None),
        "grounded_rate": metrics.rate(r["grounded"] for r in answerable),
        "refusal_accuracy": metrics.rate(r["refused"] for r in refusable),
        "false_refusal_rate": metrics.rate(r["refused"] for r in answerable),
        "p50_latency_ms": statistics.median([r["latency_ms"] for r in rows]) if rows else 0,
        "n_items": len(rows),
        "n_answerable": len(answerable),
        "n_refusable": len(refusable),
    }
    return {"summary": summary, "rows": rows}


# ---------------------------------------------------------------------------
# Contract suite
# ---------------------------------------------------------------------------
def run_contract(store, items: list[dict]) -> dict:
    """Each item: a clause + expected verdict. Measures triage precision/recall."""
    rows = []
    for item in items:
        report = rule_analyze(item["clause"], store, filename=f"{item['id']}.txt")
        findings = [f for f in report.findings if f.verdict != "not_covered"]
        predicted = findings[0].verdict if findings else "not_covered"
        expected = item["expected"]
        cited = bool(findings and findings[0].citation)
        rows.append(
            {
                "id": item["id"],
                "expected": expected,
                "predicted": predicted,
                "correct": predicted == expected,
                "cited": cited,
                "articles": [f.citation.article_no for f in findings if f.citation],
            }
        )

    # Treat "non_compliant" and "risky" as the positive class (something wrong).
    def positive(label: str) -> bool:
        return label in {"non_compliant", "risky"}

    tp = sum(1 for r in rows if positive(r["expected"]) and positive(r["predicted"]))
    fp = sum(1 for r in rows if not positive(r["expected"]) and positive(r["predicted"]))
    fn = sum(1 for r in rows if positive(r["expected"]) and not positive(r["predicted"]))
    flagged = [r for r in rows if positive(r["predicted"])]
    summary = {
        "violation_precision": metrics.safe_div(tp, tp + fp),
        "violation_recall": metrics.safe_div(tp, tp + fn),
        "citation_rate": metrics.rate(r["cited"] for r in flagged),
        "exact_match": metrics.rate(r["correct"] for r in rows),
        "n_items": len(rows),
    }
    return {"summary": summary, "rows": rows}


def gate(summary: dict, gates: dict) -> tuple[bool, list[tuple[str, float, str]]]:
    ok = True
    results = []
    for name, (threshold, op) in gates.items():
        value = float(summary.get(name, 0.0))
        passed = value <= threshold if op == "<=" else value >= threshold
        ok = ok and passed
        results.append((name, value, "PASS" if passed else f"FAIL ({op} {threshold})"))
    return ok, results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "var" / "bayyinah.db"))
    ap.add_argument("--suite", choices=["qa", "contract", "all"], default="all")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--slice", default=None)
    ap.add_argument("--fail-on-gate", action="store_true")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"database not found: {db_path}\nrun: python -m bayyinah ingest corpora/raw", file=sys.stderr)
        return 2

    store = SqliteCorpus(Database(db_path))
    if len(store) == 0:
        print("corpus is empty — ingest documents first", file=sys.stderr)
        return 2

    payload: dict = {"generated_at": datetime.now(timezone.utc).isoformat(), "chunks": len(store)}
    all_ok = True

    if args.suite in {"qa", "all"}:
        items = [GoldItem.from_dict(d) for d in load_jsonl(ROOT / "evals/gold/qa_gold.jsonl")]
        if args.slice:
            items = [i for i in items if i.category == args.slice]
        qa = run_qa(store, items, args.k, get_default_llm())
        payload["qa"] = qa
        ok, lines = gate(qa["summary"], QA_GATES)
        all_ok = all_ok and ok
        print(f"\nQA suite — {qa['summary']['n_items']} items "
              f"({qa['summary']['n_answerable']} answerable, {qa['summary']['n_refusable']} must-refuse)")
        print("-" * 58)
        for name, value, status in lines:
            print(f"{name:<24} {value:>6.3f}   {status}")
        misses = [r for r in qa["rows"] if r["answerable"] and not r["recall_at_k"]]
        if misses:
            print("\nretrieval misses:")
            for r in misses:
                print(f"  {r['id']}: got {r['retrieved']}")

    if args.suite in {"contract", "all"}:
        gold_path = ROOT / "evals/gold/contract_gold.jsonl"
        if gold_path.exists():
            contract = run_contract(store, load_jsonl(gold_path))
            payload["contract"] = contract
            ok, lines = gate(contract["summary"], CONTRACT_GATES)
            all_ok = all_ok and ok
            print(f"\nContract suite — {contract['summary']['n_items']} clauses")
            print("-" * 58)
            for name, value, status in lines:
                print(f"{name:<24} {value:>6.3f}   {status}")
            bad = [r for r in contract["rows"] if not r["correct"]]
            if bad:
                print("\nmissed clauses:")
                for r in bad:
                    print(f"  {r['id']}: expected {r['expected']}, got {r['predicted']}")

    print("-" * 58)
    print("GATE:", "PASS" if all_ok else "FAIL")

    out = ROOT / "evals/reports" / f"{datetime.now(timezone.utc):%Y-%m-%d-%H%M}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report -> {out.relative_to(ROOT)}")
    return 0 if (all_ok or not args.fail_on_gate) else 1


if __name__ == "__main__":
    raise SystemExit(main())
