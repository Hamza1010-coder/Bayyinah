# Operations runbook

## Daily

Nothing. The process is stateless except for one SQLite file.

## Weekly

```bash
python -m bayyinah stats          # queries, refusal rate, average cost
curl -s localhost:8080/api/health # corpus size
```

Watch these three numbers:

| Signal | Healthy | Meaning if it moves |
|---|---|---|
| refusal rate | 5–20% | spiking → retrieval regression or corpus change |
| p50 latency | < 300 ms (extractive) | climbing → corpus growth or a slow LLM |
| groundless answers | 0 | any non-zero is a bug; `verification_ok` should never be 0 on an answer |

## Corpus update

```bash
# 1. replace files in corpora/raw (keep provenance up to date)
python -m bayyinah ingest corpora/raw
python -m bayyinah docs
python evals/run_eval.py --fail-on-gate
```

If the eval gate fails after a corpus change, **do not ship it**. Either the gold set is stale (update it deliberately) or retrieval broke.

## Restore from backup

```bash
systemctl stop bayyinah
cp /backup/bayyinah-2026-11-10.db var/bayyinah.db
rm -f var/bayyinah.db-wal var/bayyinah.db-shm   # stale WAL will confuse SQLite
systemctl start bayyinah
curl -s localhost:8080/api/health
```

## Rotate the API key

```bash
export BAYYYINAH_API_KEY=$(openssl rand -hex 24)
docker compose up -d
```

Clients must pick up the new value; there is one key, not a keyring. That is a known limitation — see `docs/pdpl-mapping.md`.

## A user reports a wrong answer

1. Find it: `GET /api/queries`, or query the `queries` table by text.
2. Read `answer_json.meta.trace` — it records which articles were retrieved, which expansions fired, and how many verification attempts ran.
3. Classify with [failure-taxonomy.md](failure-taxonomy.md):
   - **retrieval miss** → corpus or chunking problem; add the question to the gold set first
   - **bad quote** → the verifier should already have caught it; if it didn't, that is a bug in the verifier
   - **wrong computation** → check `calc/`, add a unit test with the reported numbers
   - **should have refused** → tighten `min_evidence` / `min_term_idf`, then re-run the eval and check `false_refusal_rate`
4. Add the case to `evals/gold/qa_gold.jsonl` **before** the fix, so it fails first.

## The model is down

Symptoms: 500s on `/api/ask`, `RuntimeError: LLM call failed` in logs.

Mitigation: unset `BAYYINAH_LLM_BASE_URL` and restart. The extractive baseline answers from verbatim sentences; quality drops, availability does not. This is a deliberate graceful degradation, not a fallback hack.

## Disk full

SQLite writes fail and the API returns 500. Check `var/uploads` for orphaned files (they should be deleted immediately, but a crash mid-ingest can leave one), and prune old reports if retention requires it:

```sql
DELETE FROM contracts WHERE ts < date('now','-90 days');
DELETE FROM queries   WHERE ts < date('now','-180 days');
VACUUM;
```

## Security incident

1. Rotate `BAYYINAH_API_KEY` immediately.
2. Snapshot the database for forensics before changing anything else.
3. Read the `audit` table — every ingest, analysis and failed load is recorded with a timestamp and actor.
4. Check whether uploaded contract text remains on disk: it should not, since analysis is in-memory (`load_bytes`). Confirm no files exist in `var/uploads`.
5. Follow the breach-notification path in `docs/pdpl-mapping.md`.

## Scheduled maintenance

| Task | Frequency | Command |
|---|---|---|
| Backup | daily | `sqlite3 … ".backup …"` |
| Dependency audit | monthly | `pip-audit` / `docker scout` |
| Re-run eval | every corpus change and every model change | `python evals/run_eval.py --fail-on-gate` |
| Review gold set | monthly | add failing user questions |
| Verify restore | quarterly | restore a backup to a scratch directory |
