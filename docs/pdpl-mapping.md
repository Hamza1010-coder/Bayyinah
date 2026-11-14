# PDPL & security mapping

A one-page answer to the question an enterprise or government buyer asks before
they ask about your model: *"can we run this without our employees' data leaving
the Kingdom, and what stops it leaking?"*

This document maps intent to controls. It is **not** a compliance certification
and has not been reviewed by counsel. It is the artifact most portfolios are
missing.

## Regulatory context (verify before relying on it)

| Instrument | Relevance |
|---|---|
| **PDPL** — Personal Data Protection Law, Royal Decree No. M/19 (2021), in force Sept 2023 | Lawful basis, purpose limitation, data-subject rights, breach notification, cross-border transfer conditions |
| **PDPL Implementing Regulations** (SDAIA) | Registration, transfer assessment, sensitive-data rules |
| **NCA ECC** — Essential Cybersecurity Controls | Baseline security controls for any system handling national data |
| **NCA CCC** — Cloud Cybersecurity Controls | Applies specifically if hosted on cloud, including residency tiers |
| **Labour Law / GOSI rules** | Employment records are personal data; salaries and IDs are sensitive in practice |

> Regulatory details change. Re-check the current SDAIA publications before
> making a claim in writing.

## Control mapping

| Requirement | Control in this repo | Status |
|---|---|---|
| **Purpose limitation** | Corpus is public legislation; uploaded contracts are processed only to produce findings, never to train or to improve retrieval | by design |
| **Data minimisation** | `text/pii.py` redacts national IDs, IBANs, phones, emails, SAR amounts at the ingestion boundary, before storage or any third-party call | implemented |
| **Residency** | Core runs with no external calls; the optional LLM backend is configured by `BAYYINAH_LLM_BASE_URL` so it can point at a KSA-region endpoint or a self-hosted ALLaM server | implemented (config) |
| **Encryption in transit** | TLS terminated at the reverse proxy (Caddy/nginx); demo server is HTTP-only and binds to `127.0.0.1` | partial |
| **Encryption at rest** | Postgres disk encryption in prod; local index is plain JSONL for inspectability | not in v0.1 |
| **Access control** | No auth in the demo server (single-user, localhost). FastAPI path is ready for an auth dependency | not in v0.1 |
| **Audit trail** | Every answer carries `meta.trace` (retrieval, expansions, verification attempts), `llm` name, `latency_ms`, and corpus version | implemented |
| **Retention** | Stateless server; uploads are not persisted. A prod deployment must add a documented retention window (default 30 days) | not in v0.1 |
| **Data-subject rights** | No per-user storage in v0.1, so no deletion workflow needed yet | n/a |
| **Breach notification** | Requires an operational process, not code. Document an owner and a 72-hour path before any pilot | n/a |
| **Model-provider terms** | If a hosted API is used, confirm no-training-on-inputs and zero-retention; otherwise route contract analysis to the self-hosted path only | operator duty |
| **Prompt injection** | Contract text is untrusted. v0.1 does not isolate it from instructions — **known gap**, see `docs/failure-taxonomy.md` | not in v0.1 |

## Before a real pilot (checklist)

- [ ] Replace the synthetic corpus and record provenance for every document
- [ ] Put the API behind auth and per-tenant retrieval isolation
- [ ] Add a retention job and a documented deletion path
- [ ] Confirm the LLM endpoint's data-processing terms in writing
- [ ] Have a Saudi HR/legal practitioner review the calculators and rule set
- [ ] Write the incident-response runbook (who, when, how)
- [ ] Run a DPIA-style assessment and keep the record
