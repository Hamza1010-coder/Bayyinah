# Failure taxonomy

Ten ways this system fails, what each looks like, and what was done about it.
Five of these were found by the eval harness, not by reading the code — which is
the argument for building the harness first.

Format: **symptom → root cause → fix → regression test**.

---

## 1. Arabic punctuation absorbed into tokens

**Symptom.** A GOSI question matched a labour article on a term that looked
identical in the debugger but wasn't.

**Root cause.** `؟` (U+061F), `،` (U+060C) and `؛` (U+061B) live *inside* the
Arabic Unicode block `U+0600–06FF`. A normalizer written as
`[^\w\s\u0600-\u06FF]` therefore keeps them glued to the word:
`اجتماعيه؟` ≠ `اجتماعيه`.

**Fix.** Strip `ARABIC_PUNCT` explicitly before the general punctuation pass.

**Test.** `tests/test_normalize.py::test_arabic_punctuation_removed`

---

## 2. The definite article destroying recall

**Symptom.** "كم يوم إجازة سنوية؟" ranked Article 109 — the exact answer — last
in the top-5.

**Root cause.** `الإجازة` and `إجازة` are different BM25 terms. `ال` prefixes
roughly a third of formal Arabic words.

**Fix.** Strip a leading `ال` from tokens longer than four characters, on the
index side only.

**Test.** `tests/test_normalize.py::test_definite_article_stripped`

---

## 3. Stopwords inflating evidence scores

**Symptom.** "ما هي عقوبة عدم تسجيل العامل في التأمينات؟" was answered (wrongly)
rather than refused.

**Root cause.** The evidence gate divided matched terms by *all* terms. `في` and
`ما` matched an unrelated article, giving 2/9 ≈ 0.22 overlap — over threshold.

**Fix.** Score only `content_tokens` (stopwords and 1–2 letter noise removed),
and raise the threshold to 0.25.

**Test.** `tests/test_pipeline.py::test_out_of_corpus_question_refuses`

---

## 4. Stemming creating false friends

**Symptom.** After adding light stemming, a VAT question ("ضريبة القيمة المضافة
على الخدمات") started getting answered with labour-law articles. `الخدمات` →
`خدم` matched `خدمة` in four articles.

**Root cause.** Recall improvements cut both ways: the same rule that fixes
`ساعة`/`ساعات` also collapses unrelated vocabulary.

**Fix.** A match is only *evidence* if at least one matched term has an IDF above
a floor (0.85). A term present in most articles cannot distinguish anything.

**Test.** `tests/test_pipeline.py::test_out_of_corpus_question_refuses`

---

## 5. Register gap (colloquial vs statute)

**Symptom.** "لو استقلت بعد ست سنوات كم آخذ؟" was refused. The statute says
"ترك العامل العمل بمحض إرادته" — zero lexical overlap with `استقلت`.

**Root cause.** A hashing embedder has no semantics; the lexical path can only
match words, and users do not write like legislators.

**Fix (partial).** Query expansion: `استقل…` → append `ترك العمل بمحض إرادته`.

**Fix (real).** Swap `HashingEmbedder` for `BgeM3Embedder`. This is documented
as a known limitation rather than papered over, because the honest version of
the story is "I measured the gap and knew the fix".

**Test.** `tests/test_pipeline.py::test_every_answer_is_either_refused_or_cited`

---

## 6. Model paraphrasing instead of quoting

**Symptom.** A citation whose text was *semantically* right but not present in
the source.

**Root cause.** LLMs summarize. That is the default mode and prompting against
it is unreliable.

**Fix.** The verifier hard-fails `quote_not_verbatim`; one repair pass with the
failure reason injected; then the citation is dropped and confidence is
downgraded.

**Test.** `tests/test_verifier.py::test_paraphrased_quote_fails_hard`

---

## 7. Fabricated article numbers

**Symptom.** A citation to "المادة ٩١" when the corpus has 8 articles.

**Fix.** `article_not_found` is a hard failure and short-circuits before any
other check.

**Test.** `tests/test_verifier.py::test_nonexistent_article_fails_hard`

---

## 8. Uncited article references in prose

**Symptom.** The answer says "وفقاً للمادة ٨٥" but the citations list only 84.

**Fix.** Soft finding `uncited_article_reference`: recorded, shown in the audit
trail, does not block. Soft rather than hard because the model may legitimately
*mention* an article it is contrasting with.

**Test.** `tests/test_verifier.py::test_uncited_article_reference_is_soft`

---

## 9. Arithmetic drifting into the model

**Symptom.** A plausible but wrong end-of-service amount.

**Root cause.** LLMs are bad at multi-step arithmetic and confident about it.

**Fix.** Amounts never come from the model. `maybe_calculate` extracts
`(salary, years, reason)` by regex, `calc/eos.py` computes, and the result is
injected as a fixed string the model may only restate.

**Test.** `tests/test_calc.py` (12 cases) + `tests/test_pipeline.py::test_end_of_service_question_is_grounded_and_calculated`

---

## 10. Over-refusal

**Symptom.** A question the corpus *does* answer gets refused.

**Root cause.** Every gate is a precision/recall trade. Raising the evidence
threshold to block out-of-corpus questions also blocks weakly-phrased ones.

**Fix.** Monitored as a first-class metric (`false_refusal_rate`, gate ≤ 0.10)
rather than ignored. It is currently 0.000 on the gold set — which is a small
sample, not a guarantee.

**Test.** `evals/run_eval.py` gate.

---

## Not yet handled

| Failure | Status |
|---|---|
| Stale law after an amendment | Needs the change-monitoring job (MVP §18) |
| OCR errors on scanned contracts | No OCR in v0.1; the API takes text |
| Prompt injection inside a contract document | Text is not yet isolated from instructions |
| Mixed AR/EN contracts | Chunked as one language |
| Multi-hop questions needing the Implementing Regulations *and* the Law | Corpus has only the Law |
