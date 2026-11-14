# Architecture

## Layers

```
┌──────────────────────────────────────────────────────────────┐
│  apps:  web UI (static)  ·  CLI (bayyinah ...)              │
├──────────────────────────────────────────────────────────────┤
│  api/app.py       routing · auth · rate limit · multipart    │
├──────────────────────────────────────────────────────────────┤
│  services.py      AnswerService · ContractService · stats    │
│                   logs every question, prices every call     │
├──────────────────────────────────────────────────────────────┤
│  generation/      pipeline · prompts · llm · verifier        │
│  contracts/       xray rules · analyzer · reports            │
│  guardrails/      refusal policy                             │
├──────────────────────────────────────────────────────────────┤
│  retrieval/       corpus · fusion · bm25 · embed · expand    │
├──────────────────────────────────────────────────────────────┤
│  text/            normalize · chunker · pii                  │
├──────────────────────────────────────────────────────────────┤
│  db.py            SQLite: documents, chunks, FTS5, audit    │
└──────────────────────────────────────────────────────────────┘
```

Dependencies point **downward only**. `text/` knows nothing about SQL; `retrieval/` knows nothing about HTTP; `generation/` receives a corpus object that must satisfy four methods. That is what makes the pipeline testable without a server, a database, or a network.

## Data flow — a question

```
question
  → guardrails.pre_check         jurisdiction? unlawful intent?  ──→ refusal
  → retrieval.expand             "استقلت" → "ترك العمل بمحض إرادته"
  → corpus.search                FTS5 top-40  +  dense top-40
  → fusion.rrf                   1/(60+rank), lexical weight 1.0, dense 0.4
  → fusion.rerank                IDF-weighted overlap + bigram phrase bonus
  → evidence gate                overlap ≥ 0.25  AND  some term IDF ≥ 0.85
  → llm.generate                 JSON only: answer + citations + confidence
  → verifier.verify              article exists? quote is a substring?
  → (one repair pass)            failures injected back into the prompt
  → calc.eos                     if numeric: deterministic, model may restate
  → services.AnswerService       log query, price it, return
```

Each arrow is a named function with its own test. The failure of any stage is attributable and reproducible.

## Data flow — a document

```
file bytes ──→ ingest.loaders.load_bytes      txt / md / docx / pdf / html
           ──→ text.chunker.chunk_document    split on المادة, heading in the key
           ──→ text.normalize                 aggressive key + untouched display
           ──→ embedder.embed                 hashing (default) or BGE-M3
           ──→ db.add_chunk                   chunks + FTS5 row + term/df rows
           ──→ db.audit                       who ingested what, when
```

Re-ingesting an unchanged file is a no-op (sha256). Re-ingesting a changed file replaces that document's chunks; no duplicates, no ghosts in the FTS index.

## Why two normalizers

| | `normalize_for_index` | `normalize_for_match` |
|---|---|---|
| purpose | maximize recall | prove a quote is verbatim |
| diacritics | stripped | stripped |
| alef forms | unified | unified |
| ta marbuta | `ة → ه` | **preserved** |
| definite article | stripped | preserved |
| plural/feminine suffix | light-stemmed | preserved |
| digits | ASCII | ASCII |

If the verifier used the aggressive normalizer, "خدمه" would match "خدمة" and the central guarantee would silently break. If retrieval used the conservative one, half the vocabulary would fail to match. Two functions, deliberately different, documented where people will read them.

## Retrieval scoring

Reciprocal Rank Fusion is used rather than score averaging because BM25 and cosine live on incomparable scales and per-query normalization is a tuning trap:

```
score(d) = Σ_r  weight_r / (60 + rank_r(d))
```

Then a rerank pass, because rank fusion alone cannot tell "مكافأة نهاية الخدمة" from "مدة الخدمة":

```
rerank(d) = rrf(d)
          + Σ_{t ∈ q∩d} idf(t) / Σ_{t ∈ q} idf(t)
          + 0.75 · |bigrams(q) ∩ bigrams(d)| / |bigrams(q)|
```

The IDF term is the important one. Without it, a query term present in every article outvotes the one term that actually identifies the answer.

## Evidence gate

Retrieval always returns *something*. A gate decides whether anything returned is good enough to answer from:

1. **Overlap** — share of the question's content terms present in a retrieved chunk, ≥ 0.25.
2. **Distinctiveness** — at least one matched term with `idf ≥ 0.85`. A term in most articles cannot distinguish anything.

Failing either produces a refusal, not a guess. The gate is measured continuously as `false_refusal_rate` (≤ 0.10) because precision and recall trade against each other here.

## Storage schema

| Table | Purpose |
|---|---|
| `documents` | one row per ingested file: hash, issuer, version, provenance JSON |
| `chunks` | article-level text: display (verbatim), normalized key, vector blob |
| `chunks_fts` | FTS5 index over the normalized key |
| `chunk_terms` | term ↔ chunk, for document frequencies |
| `queries` | every answered question + verification, latency, cost |
| `contracts` | stored reports, downloadable later |
| `feedback` | was this useful |
| `audit` | ingest, analysis, failures |

Vectors are stored as `array('f')` blobs and loaded into memory at startup. At 2,000 chunks × 512 dims that is ~8 MB — far cheaper than a round trip per query.

## Scaling path

The current design holds until roughly 10⁵ chunks on one box. Beyond that:

| Symptom | Move to |
|---|---|
| Writes block reads | PostgreSQL + `pgvector`, `tsvector` GIN index |
| Dense scan dominates | HNSW index in pgvector, or a dedicated vector store |
| Rebuild is slow | incremental re-index keyed on `documents.sha256` |
| One process can't serve | stateless API replicas + shared Postgres |
| Need multi-tenant isolation | `tenant_id` on every table + row-level security |

The SQL shape in `db.py` is deliberately portable: the FTS5 query and the fusion logic are the only SQLite-specific parts, and both have direct Postgres equivalents.

## Failure containment

- A document that fails to load is **reported**, never half-ingested.
- A citation that fails verification is **dropped**, and if none survive the answer becomes sources-only.
- An LLM timeout degrades to the extractive baseline's behaviour (sources without synthesis) rather than a 500.
- A missing `python-docx` degrades DOCX export to HTML with an explicit 501, not a crash.
