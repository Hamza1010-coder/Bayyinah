# API

Base URL: `http://127.0.0.1:8080`

Auth: when `BAYYINAH_API_KEY` is set, send `X-API-Key: <key>`. Public endpoints are `/`, `/api/health`, `/api/ask`, `/api/contracts*`, `/api/queries`, `/api/documents`. Protected: `/api/stats`, `/api/ingest`.

Rate limit: `BAYYINAH_RATE_LIMIT` requests per minute per key or IP. Exceeding it returns `429` with `retry_after_s`.

All responses are JSON except the report downloads. Errors are `{"error": "..."}`.

---

## `GET /api/health`

```json
{
  "status": "ok",
  "chunks": 8,
  "documents": 1,
  "synthetic_corpus": true,
  "auth_required": false,
  "model": "extractive-baseline",
  "started_at": "2026-11-11T07:49:12+00:00"
}
```

---

## `POST /api/ask`

```bash
curl -s localhost:8080/api/ask -H 'Content-Type: application/json' \
  -d '{"question":"كم مكافأة نهاية الخدمة إذا استقلت بعد 3 سنوات براتب 6000 ريال؟"}'
```

```json
{
  "answer": {
    "question": "…",
    "answer_ar": "إذا ترك العامل العمل بمحض إرادته استحق …",
    "answer_en": "",
    "citations": [
      {"doc_id": "labor_law_sample_synthetic", "article_no": "85",
       "quote": "إذا ترك العامل العمل بمحض إرادته …", "page": 0, "url": "", "title": ""}
    ],
    "calculations": [
      {"kind": "end_of_service", "inputs": {"salary": 6000, "years": 3, "reason": "resignation"},
       "result": 3000.0, "unit": "SAR", "formula_ref": "art_84+art_85",
       "trace": ["المكافأة الأساسية (المادة ٨٤): 9,000.00 ر.س", "…"]}
    ],
    "confidence": "medium",
    "refusal": null,
    "refusal_reason": null,
    "risk_flags": ["resignation", "financial_liability"],
    "requires_human_review": false,
    "disclaimer_required": true,
    "verification": [],
    "meta": {"trace": [...], "latency_ms": 11.0, "model": "extractive-baseline"}
  },
  "query_id": 1,
  "latency_ms": 11.0,
  "cost_usd": 0.000344,
  "model": "extractive-baseline",
  "markdown": "…rendered answer…",
  "synthetic_corpus": true
}
```

`refusal_reason` is one of `out_of_scope`, `unlawful_intent`, `no_evidence`, `unverified`. When it is set, `citations` is empty and the UI shows the refusal instead of an answer.

Errors: `400` for a question shorter than 3 chars or longer than 1000.

---

## `POST /api/contracts`

Three accepted bodies.

**JSON text**

```bash
curl -s localhost:8080/api/contracts -H 'Content-Type: application/json' \
  -d '{"text":"البند 1: فترة التجربة ستة أشهر.","filename":"عقد.txt"}'
```

**Base64 file**

```bash
curl -s localhost:8080/api/contracts -H 'Content-Type: application/json' \
  -d "{\"filename\":\"c.docx\",\"content_base64\":\"$(base64 -w0 c.docx)\"}"
```

**Multipart upload** (what the UI does)

```bash
curl -s localhost:8080/api/contracts -F 'file=@c.docx'
```

Response:

```json
{
  "contract_id": "8f14e45f-…",
  "filename": "عقد.txt",
  "report": {
    "document_id": "…",
    "filename": "عقد.txt",
    "counts": {"non_compliant": 3, "risky": 0, "compliant": 0, "not_covered": 0},
    "findings": [
      {"clause_id": "c-001", "clause_text": "تكون فترة التجربة ستة أشهر.",
       "verdict": "non_compliant", "severity": "high",
       "rationale": "فترة التجربة المذكورة (180 يوماً) تتجاوز الحد النظامي ٩٠ يوماً.",
       "suggested_redline": "…", "citation": {"article_no": "53", "quote": "…"}, "confidence": 0.9}
    ],
    "redaction": {"MONEY": 1},
    "notes": []
  },
  "redaction": {"MONEY": 1},
  "coverage": {"clauses": 3, "covered_by_rules": 3, "covered_by_llm": 0, "uncovered": 0},
  "links": {"html": "/api/contracts/<id>/report.html", "docx": "/api/contracts/<id>/report.docx"}
}
```

Errors: `400` for text under 40 chars, `415` for an unsupported or unreadable file type.

---

## `GET /api/contracts`

```json
{"contracts": [{"id": "8f14…", "ts": "2026-11-11T07:49:12+00:00",
                "filename": "عقد.txt", "counts": {"non_compliant": 3}}]}
```

## `GET /api/contracts/{id}`

Full stored report (same shape as the creation response).

## `GET /api/contracts/{id}/report.html`
Standalone RTL HTML, printable. **Requires no auth**, so links can be shared — add auth before exposing this publicly.

## `GET /api/contracts/{id}/report.docx`
Word document, right-to-left paragraphs. Returns `501` if `python-docx` is not installed.

---

## `GET /api/queries?limit=50`

Recent questions with verification outcome, latency and cost.

```json
{"queries": [{"id": 3, "ts": "…", "question": "…", "refusal_reason": null,
              "confidence": "medium", "latency_ms": 11.0, "cost_usd": 0.000344,
              "n_citations": 2, "verification_ok": true}]}
```

## `POST /api/feedback`

```bash
curl -s localhost:8080/api/feedback -H 'Content-Type: application/json' \
  -d '{"target_type":"query","target_id":"1","useful":true,"comment":"دقيق"}'
```

## `GET /api/documents`

Ingested corpus documents with chunk counts, language and the synthetic flag.

## `GET /api/stats` 🔒

```json
{"chunks": 8, "documents": 1,
 "queries": {"total": 12, "refused": 3, "avg_latency_ms": 12.4, "avg_cost_usd": 0.00031},
 "feedback": {"total": 4, "useful_rate": 0.75}}
```

## `POST /api/ingest` 🔒

```bash
curl -s localhost:8080/api/ingest -H 'X-API-Key: …' -H 'Content-Type: application/json' \
  -d '{"path":"corpora/raw"}'
```

Ingests a file or directory **on the server's filesystem**. Intended for operators, not end users; exposing it to untrusted callers is a path-traversal hole. It is not enabled by default and requires the key.
