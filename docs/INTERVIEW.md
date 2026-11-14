# Interview notes

The questions this project invites, with answers you can actually defend. If you
cannot explain an answer in your own words, delete the feature rather than
memorise the line — an unexplainable repo is worse than a small one.

---

## Retrieval

**Why hybrid instead of just embeddings?**
Legal Arabic has exact terms that users type verbatim (`مكافأة نهاية الخدمة`,
`المادة ٨٥`). Embeddings smooth over those; BM25 nails them. Dense handles
paraphrase. Running both and fusing beats either, and it costs one extra query
against an index I already have.

**Why RRF and not score averaging?**
BM25 and cosine live on incomparable scales, so averaging needs per-query
normalisation, which is a tuning trap that breaks on the next corpus. RRF only
uses ranks, so it needs no calibration and stays stable. The one knob is weight:
I down-weight dense to 0.4 because the default embedder is weak, and a weak
retriever's ranks are noise.

**What does the reranker actually do?**
IDF-weighted term overlap plus a bigram phrase bonus. Unweighted overlap
promotes generic articles — every article contains "العامل", so a term present
everywhere outvotes the one term that identifies the answer. Bigrams separate
"مكافأة نهاية الخدمة" from "مدة الخدمة", which share a word but are different
legal concepts.

**You don't have a cross-encoder.**
Correct, and it's a documented gap. `bge-reranker-v2-m3` is a drop-in in
`retrieval/`, but adding it would have required a GPU dependency before the eval
could tell me whether it helped. Measure first.

## Grounding

**How do you stop hallucinated citations?**
Two hard checks in code: the article must exist in the corpus, and the quoted
span must be a verbatim substring after conservative normalisation. If either
fails, I regenerate once with the failure injected into the prompt; if it fails
again, the citation is dropped and the answer degrades to sources-only.

**Why not just tell the model to cite?**
Because that's a wish, not a control. A prompt can be ignored, and you cannot
tell from the output whether it was. A function that fails the answer is a
control, and it's testable — `test_paraphrased_quote_fails_hard` exists for
exactly that.

**Why does the verifier use a different normaliser than retrieval?**
Because they answer different questions. Retrieval asks "does this text mean the
same thing" and should fold aggressively. Verification asks "is this exact text
present" and must not fold letters, or a paraphrase containing `خدمه` would pass
against a source containing `خدمة`. Same file, two functions, documented.

**The model does the maths?**
Never. `maybe_calculate` extracts salary/years/reason by regex, `calc/eos.py`
computes with unit tests, and the result is injected as a fixed string the model
may only restate. The arithmetic trace is shown to the user so they can check it.

## Evaluation

**What do you measure?**
Retrieval recall@5 and MRR; citation validity (hard) and precision; refusal
accuracy and false-refusal rate; contract violation precision/recall; latency and
cost. Gates are numeric and CI-blocking.

**Why is refusal a metric?**
Because every gate trades precision for recall. If I only measure "did it answer
correctly", I can improve the score by refusing everything. False-refusal rate is
the counterweight, and it's a hard gate at ≤ 0.10.

**Your scores are 1.0 — that's suspicious.**
They're 1.0 on 20 synthetic questions, which proves the harness works, not that
the system is accurate. The README says this explicitly wherever the numbers
appear. The honest number arrives when the real corpus lands, and it will be
lower.

**How do you know the gold set isn't overfitted?**
I wrote it before the fixes, and several items failed loudly — the refusal slice
went 0.75 → 1.00 because the eval found a real defect, not because I tuned to it.
The next step is holding out 20% and adding questions from real users, who phrase
things I would never invent.

## Product and refusals

**Why refuse instead of answering with low confidence?**
For a compliance tool, a confident wrong answer is worse than silence: the user
forwards it to their GM. Refusal plus an escalation path is the safe failure
mode, and it's cheap to implement once refusal is treated as a feature.

**What happens when the model paraphrases?**
The citation fails verification, gets dropped, and if nothing survives the answer
becomes "here are the relevant articles, I can't verify a synthesis". That's the
product working, not failing.

**Why rules before the LLM in the X-Ray?**
Rules are free, instant, deterministic and testable, and they catch the four
violations that cause most real disputes. Putting the LLM first would make the
audit non-deterministic and slow for no gain. The model only sees clauses the
rules missed, and its output goes through the same verifier.

## Engineering

**Why SQLite?**
It's stdlib, it ships FTS5 (real BM25), it survives restarts, and it makes
`git clone && run` two commands. The schema and query shapes are portable to
Postgres, and the scaling path is written down.

**Why no LangChain?**
The pipeline is eight named functions with measurable per-stage latency. A
framework abstraction would hide exactly the thing I need to debug and defend. I
would reach for one when orchestration becomes genuinely multi-step.

**Why is the core stdlib-only?**
So a reviewer can run it in one command without a virtualenv, a key, or a GPU.
That constraint forced better isolation — the LLM, embeddings, DOCX and PDF paths
are all optional adapters behind interfaces, which is what I'd want anyway.

**Uploads never touch disk — why does that matter?**
An employment contract contains names, national IDs and salaries. Parsing from a
byte buffer means there's nothing to retain, forget to delete, or leak, and no
temp-file cleanup path to get wrong. It also removed a whole class of Windows
permission bugs.

## The honest ones

**What would you do differently?**
Start with the real corpus on day one. Building against a fixture I wrote let me
tune to my own phrasing, and the first real text immediately broke the article
parser — a bug 163 tests had not caught because the tests shared my assumption.

**What's the weakest part?**
The dense retriever. It's a hashing baseline, so genuinely semantic paraphrase
fails and I compensate with query-expansion rules. They work, but they're a
crutch, and I know it.

**Is this production ready?**
No. Single-tenant, single-writer, no auth beyond a shared key, no OCR. What is
production-grade is the *discipline*: verification, gates, audit, and documented
failure modes.

**What did you cut, and why?**
Fine-tuning (no data to justify it), agents (the task is a fixed pipeline),
multi-tenancy (no tenants yet), and a React frontend (a single HTML file is
faster to change and easier to inspect). Each cut is in `DECISIONS.md`.
