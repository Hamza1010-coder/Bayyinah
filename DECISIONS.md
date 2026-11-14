# Decisions

Short ADRs. Each records what was chosen, what was rejected, and what would
make us revisit. This file exists because "why didn't you use LangChain?" is a
better interview question than "what does it do?"

---

## ADR-001 — Stdlib-only core, no framework

**Context.** The repo has to run on a reviewer's machine in one command.

**Decision.** Text, retrieval, generation, calc and eval are dependency-free
Python 3.10+. FastAPI, sentence-transformers and torch are optional extras.

**Rejected.** FastAPI-first with pydantic models, pytest, LangChain.

**Consequences.** `python -m bayyinah.api.serve` works with no install. Tests
use `unittest`. We lose pydantic validation and FastAPI's OpenAPI docs on the
demo path — `api/main.py` keeps the FastAPI version for production.

**Revisit if.** The team grows past one and onboarding friction stops mattering.

---

## ADR-002 — Two normalizers (index vs match)

**Decision.** `normalize_for_index` is aggressive (alef folding, ta-marbuta
folding, definite-article stripping, light stemming, Arabic punctuation
removal). `normalize_for_match` is conservative and preserves letter identity.

**Why.** The citation verifier asks "is this quote verbatim?". If the verifier
used the aggressive normalizer, a paraphrase containing `خدمه` would match a
source containing `خدمة` and the core guarantee would quietly break. Retrieval
has the opposite requirement: maximize recall.

**Consequences.** Two functions to keep straight, and a per-field decision about
which to use. The cost of getting it wrong is invisible until it isn't.

---

## ADR-003 — pgvector over a dedicated vector database

**Decision.** Postgres + pgvector + `tsvector` in one instance.

**Rejected.** Qdrant, Weaviate, OpenSearch.

**Why.** The corpus is ~500k tokens. One database means one backup story, one
connection pool, one thing to host in-Kingdom, and hybrid retrieval in a single
SQL statement.

**Revisit if.** > 50M chunks, or sub-50ms p99 becomes a hard requirement.

---

## ADR-004 — No fine-tuning in v1

**Decision.** Retrieval + prompting only.

**Why.** With 150 eval items we cannot distinguish a fine-tune from noise, and
a fine-tune cannot cite. Fixing a bad answer by editing the corpus is an
afternoon; fixing it by retraining is a week and a regression risk.

**Revisit if.** 2k+ real queries show a systematic style/format failure that
prompting cannot fix, *and* we have a held-out set large enough to prove the win.

---

## ADR-005 — Deterministic pipeline, not an agent

**Decision.** Fixed stages: guardrail → retrieve → gate → generate → verify →
repair → calculate → assemble.

**Why.** Each stage has its own latency, cost and failure mode, and each is
independently testable. An agent loop would trade all of that for flexibility we
do not need — the task is "find the article, quote it, compute if numeric".

**Revisit if.** Users need multi-turn document gathering ("now check the GOSI
registration for this employee"), which is a genuine planning problem.

---

## ADR-006 — Citations verified in code

**Decision.** A citation passes only if (a) the article exists in the corpus and
(b) the quote is a normalized substring of the stored display text.

**Why.** "Cite your sources" in a prompt is a wish. A function that fails the
answer is a control. This single decision is what makes the product defensible
in a legal-adjacent domain, and it is the first thing a technical interviewer
will probe.

**Consequences.** Some legitimate answers get downgraded when the model
paraphrases. That is the correct trade: silence beats a confident wrong answer.

---

## ADR-007 — Synthetic corpus in the repo

**Decision.** Ship an 8-article synthetic fixture, clearly labelled, instead of
scraping the statute.

**Why.** Reproducibility without redistribution questions, and it forces the
tests to be about *mechanism* (chunking, verification, gates) rather than about
memorizing one article.

**Consequences.** Every number in the README is a mechanism measurement, not an
accuracy claim. That is stated explicitly wherever the numbers appear.

**Revisit.** Immediately, for any real deployment. See `PROVENANCE.md`.

---

## ADR-008 — SQLite as the system of record

**Decision.** One SQLite file holds documents, chunks, the FTS5 index, term
frequencies, queries, reports and the audit log.

**Rejected.** Postgres from day one; JSONL files plus an in-memory index.

**Why.** It is stdlib, it ships FTS5 (real BM25, not a toy), it survives restarts,
and it makes `git clone && run` a two-command experience. JSONL dies on the first
concurrent write and gives no query/audit history — and the audit history is a
product feature, not an implementation detail.

**Consequences.** Single-writer concurrency, no horizontal scale-out, and no
migrations framework. All three are acceptable below ~10⁵ chunks and all three
have a documented exit (`docs/ARCHITECTURE.md`).

**Revisit if.** Multiple API replicas are needed, or write contention appears.

---

## ADR-009 — Loaders operate on bytes, never temp files

**Decision.** `load_bytes(data, filename)` is the primitive; `load(path)` reads
the file and delegates. Contract uploads are parsed from an in-memory buffer.

**Why.** Three reasons, in order of importance:

1. **Privacy.** An uploaded employment contract containing an ID number never
   touches disk, so there is nothing to retain, forget to delete, or leak.
2. **Correctness.** No cleanup path to get wrong on a crash mid-request.
3. **Simplicity.** No temp-directory configuration, no cross-platform path
   issues, no permission edge cases.

**Consequences.** A 5 MB upload lives in memory for the duration of the request —
bounded by `BAYYINAH_MAX_UPLOAD_BYTES`. Corpora files are still read from disk,
because they are operator-supplied, not user-supplied.

---

## ADR-010 — Rules before LLM in contract analysis

**Decision.** Deterministic rules run first; the LLM is a second pass over only
the clauses the rules left uncovered.

**Why.** The rules are free, instant, deterministic and testable, and they catch
the four violations that account for most real disputes. Putting the LLM first
would make the audit path non-deterministic, slow, and expensive — and would give
up the "same input, same finding" property that a compliance tool needs.

**Consequences.** The rule set is limited and must be extended deliberately (each
addition gets a test and a gold-set entry). LLM findings are accepted only when
their quote verifies against the cited article.
