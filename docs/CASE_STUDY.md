# Case study — Bayyinah

*A portfolio write-up. If you are reviewing this repo, start here and then read
[DEMO.md](DEMO.md) for the recorded run.*

---

## The one-liner

An Arabic-first compliance copilot for Saudi employment law that answers only
when it can cite the article, verifies every quote character-by-character, and
computes money in deterministic code instead of asking a model.

## The problem

Saudi SMEs get fined and dragged into labour disputes because their HR teams
cannot quickly answer "does this comply?". The knowledge is public — roughly 250
articles of dense legal Arabic — but it lives in PDFs and web pages, not in
anything queryable. Generic chat models answer confidently, without citations,
and sometimes wrongly, which in a compliance context is worse than silence.

**User:** an HR manager at a 60-person firm who handles hiring, Qiwa, GOSI and
payroll alone. She reads Arabic natively, works on a phone as often as a laptop,
and needs something she can forward to her GM.

## What I built

Three surfaces on one engine:

1. **Ask** — bilingual Q&A over the statute; every answer carries article-level
   citations.
2. **X-Ray** — paste or upload a contract, get clause-level violations bound to
   articles, plus a downloadable Word/HTML report.
3. **Audit trail** — every question logged with retrieval trace, verification
   outcome, latency and cost.

## The five decisions that mattered

**1. Citations are verified in code, not requested in a prompt.**
A citation passes only if the article exists in the corpus *and* the quoted span
is a verbatim substring of the stored text. Failing that, the answer is
regenerated once and then downgraded to sources-only. This is the single
decision the whole product rests on, and it is 60 lines of Python.

**2. Two normalizers, deliberately different.**
Retrieval strips diacritics, folds alef forms, drops the definite article and
lightly stems — because `الإجازة` must match `إجازة`. Verification does *not*
fold letters, because if it did, a paraphrase could pass as a quote. Getting
these confused silently breaks the guarantee, so the distinction is documented
at the top of the file and tested from both sides.

**3. The model never does arithmetic.**
End-of-service amounts come from `calc/eos.py`: unit-tested, trace-printed,
reviewable by an HR practitioner. The model's only job is to restate the result.
An LLM can be plausible and wrong about a number; a function cannot.

**4. Refusals are a first-class feature with their own test set.**
Retrieval always returns *something*. So a gate decides whether anything is good
enough: content-token overlap ≥ 0.25 **and** at least one matched term with
IDF ≥ 0.85. Below that, the system refuses and says why (`out_of_scope`,
`no_evidence`, `unlawful_intent`). Over-refusal is tracked as a metric, because
every gate trades precision against recall.

**5. Rules before LLM in contract analysis.**
Four deterministic checks catch the highest-frequency violations (probation over
90 days, waiver of end-of-service pay, >48h weeks, <21 days leave) in
microseconds with no hallucination risk. The LLM runs only on clauses the rules
left uncovered, and only its verified quotes survive.

## What the numbers say — and what they do not

| Metric | Value |
|---|---|
| Retrieval recall@5 | 1.00 |
| MRR | 0.97 |
| Citation validity (hard) | 1.00 |
| Refusal accuracy | 1.00 |
| False refusal | 0.00 |
| Contract violation P / R | 1.00 / 1.00 |
| Tests | 163 |

**These are mechanism measurements, not accuracy claims.** The shipped corpus is
a synthetic fixture, and the README says so on every surface that touches it. The
eval harness is the deliverable at this size: it proves the invariants hold (no
unverified citations, no ungrounded answers, refusals where evidence is missing)
and it gates CI, so a regression blocks the build.

## What the eval caught (real bugs, not decoration)

- Arabic punctuation (`؟`, `،`) lives *inside* the Unicode Arabic block, so a
  naive filter left it glued to tokens — a GOSI question started matching labour
  articles.
- The definite article `ال` broke recall: `الإجازة` and `إجازة` were unrelated
  BM25 terms. Articles ranked dead last.
- Stopwords inflated the evidence score, so out-of-corpus questions were
  answered instead of refused.
- Light stemming created false friends: `الخدمات` → `خدم` made a **VAT question**
  match employment law. Fixed with a minimum-IDF requirement.
- Register gap: "لو استقلت…" was refused because the statute says "ترك العمل
  بمحض إرادته". Patched with query expansion, and documented as the reason a
  real embedding model is the correct fix.

The full list is in [failure-taxonomy.md](failure-taxonomy.md).

## The bug that only real data exposed

The official statute numbers its articles **in words**: `المادة الثانية والعشرون`.
My chunker only accepted digits, so pointing it at real text would have produced
one giant "article 0" — silently, with retrieval still returning results.

I added a compositional parser (`arabic_numbers.py`) that sums units, tens and
hundreds, strips amendment badges glued to the heading (`الثانية عشرةمعدلة — …`),
and distinguishes a heading from a prose mention (`المادة التي تنظم …`).
`scripts/import_law.py` then converts a saved copy of the official page into a
clean corpus file, reporting article counts and gaps so a partial download is
visible rather than silent.

## What I would do next

1. **Ingest the real statute end to end.** The importer + parser are ready; the
   remaining step is saving the official page (the site is not scrapeable
   automatically, and scraping legislation is a bad idea anyway). Re-run the
   eval and publish the drop honestly.
2. **Swap the hashing embedder for BGE-M3**, then delete the query-expansion
   stopgap it currently needs.
3. **OCR path** for scanned Arabic contracts, with a measured character error
   rate rather than a promise.
4. **Two pilot users**, and a redline generator that emits a corrected `.docx`.

## What I learned

The engineering is the easy part. The hard part is deciding what the system must
refuse to do, and then proving it doesn't do those things. A demo that always
answers is not a product; a product knows when to stop.
