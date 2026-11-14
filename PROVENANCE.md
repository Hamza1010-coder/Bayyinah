# Provenance

Every document in `corpora/raw/` must have a row here **before** it is ingested.
If a reviewer asks "where did this text come from and are you allowed to use
it?", this file is the answer.

## Currently ingested

| File | Issuer | Version / date | Source URL | Licence / terms | Status |
|---|---|---|---|---|---|
| `labor_law_sample_SYNTHETIC.txt` | — | generated 2026-11-11 | — | synthetic, generated for this repo | ⚠️ **TEST FIXTURE — NOT LEGAL TEXT** |

> The bundled corpus is synthetic. It exists so the pipeline, verifier and eval
> harness can be exercised without redistributing a statute. Replace it before
> showing output to anyone who might act on it.

## Adding the real statute (recommended, ~5 minutes)

The Labor Law is published by the Bureau of Experts at the Council of Ministers
and mirrored, article by article, by the [arbiter.sa](https://law.arbiter.sa)
portal, which cites the Bureau as its source and tracks amendments.

1. Open the law page in a browser and save the **complete** page (`Ctrl+S` →
   "Webpage, HTML only"). Saving only the visible part gives you a partial file.
2. Convert and inspect:

   ```bash
   python scripts/import_law.py path/to/saved.html --out corpora/raw/labor_law.txt
   ```

   The importer strips editorial chrome ("معدلة — المرسوم الملكي رقم…",
   "هل هناك خطأ؟ أبلغنا") and reports the article count plus any gaps. A correct
   import should report **252 articles, first 1, last 252**.
3. Record the row below, delete the synthetic fixture, then re-ingest and
   re-run the eval:

   ```bash
   rm corpora/raw/*SYNTHETIC*
   python -m bayyinah ingest corpora/raw
   python evals/run_eval.py --fail-on-gate
   ```

Expect the eval numbers to **drop**. That drop is the honest result and belongs
in the README — a repository that only reports 1.000s on synthetic data is not
reporting anything.

**Do not** scrape the portal automatically. It is a third-party mirror behind a
browser, its terms are not a bulk-download licence, and silently caching
legislation is how people end up shipping a stale or partial copy without
noticing. One deliberate save, with a report you read, is the defensible path.

## Template row for the real corpus

| File | Issuer | Version / date | Source URL | Licence / terms | Status |
|---|---|---|---|---|---|
| `labor_law.txt` | هيئة الخبراء بمجلس الوزراء (via arbiter.sa mirror) | 1426/08/23هـ — 27/09/2005م، 252 مادة، 105 معدلة | *(paste the exact URL you saved)* | public legislation; mirror terms not a bulk licence | ✅ real |

## Adding the real corpus

Official Saudi legislation is published by the Bureau of Experts at the Council
of Ministers (هيئة الخبراء بمجلس الوزراء) and by the Ministry of Human Resources
and Social Development. Government legislation is public, but **check the terms
of the specific portal you copy from**, and do not ingest paywalled commentary
or a law firm's annotated text.

For each document, record:

| Field | Example |
|---|---|
| File name | `labor_law_1445.txt` |
| Issuer | Bureau of Experts |
| Version / date | as printed on the document |
| URL | direct link you fetched from |
| Retrieved at | ISO date |
| Licence / terms | what the portal states |
| Notes | amendments, repealed articles, translation caveats |

## Rules

1. **Never ingest text you cannot cite a source for.** Retrieval quality is worthless if the source is unverifiable.
2. **Version everything.** A statute that changed last month makes last month's answers wrong, not just stale.
3. **Keep Arabic and English separate documents.** A "bilingual" PDF with two columns produces garbage chunks; ingest each language as its own file and set `lang` accordingly.
4. **Do not scrape aggressively.** Cache locally, respect `robots.txt`, and prefer an official bulk download or API over crawling.
