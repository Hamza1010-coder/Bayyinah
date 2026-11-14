# Live demo

A recorded run of the actual product, not a mock-up. Reproduce it in two terminals.

```bash
# terminal 1
python -m bayyinah serve

# terminal 2
python scripts/demo.py
```

The transcript below is from a run against the shipped synthetic corpus, with
the offline extractive baseline (no LLM configured).

---

## 1. Health

```
chunks       : 8
documents    : 1
model        : extractive-baseline
synthetic    : True
auth required: False
```

The `synthetic` flag is not decoration: the bundled corpus is 8 test articles,
and every surface that consumes it says so.

## 2. Grounded answer + deterministic calculation

Ask: **كم مكافأة نهاية الخدمة إذا استقلت بعد 3 سنوات براتب 6000 ريال؟**

```
calc (art_84+art_85):
   المكافأة الأساسية (المادة ٨٤): 9,000.00 ر.س
   نسبة الاستحقاق عند الاستقالة (المادة ٨٥): 1/3
   => 3,000.00 SAR

cite: article 85 | إذا ترك العامل العمل بمحض إرادته استحق من مكافأة نهاية الخدم…
cite: article 84 | يستحق العامل عند انتهاء علاقة العمل مكافأة نهاية الخدمة، وتُ…

verified=True  confidence=medium  latency=18.7ms  cost=$0.000344
```

What to notice:

- the amount came from `calc/eos.py`, not from the model;
- both citations are verbatim substrings of the stored article text;
- `verified=True` means the verifier found no hard failures.

## 3. Refusal — foreign jurisdiction

Ask: **كم مدة الإشعار في قانون العمل الإماراتي؟**

```
refusal_reason: out_of_scope
citations     : 0
text          : لا أستطيع الإجابة عن هذا السؤال: نطاقي يقتصر على نظام العمل السعودي…
```

A retrieval-first system would have answered this with Saudi law. The guardrail
runs before retrieval for exactly that reason.

## 4. Refusal — no evidence

Ask: **ما هي عقوبة عدم تسجيل العامل في التأمينات الاجتماعية؟**

```
refusal_reason: no_evidence
citations     : 0
```

The corpus has no GOSI penalty provisions. The system says so instead of
retrieving a semantically adjacent article about "التأمينات".

## 5. Contract X-Ray

Paste a 7-clause contract:

```
4 non-compliant · 1 risky · 2 not covered
coverage: {'clauses': 7, 'covered_by_rules': 5, 'covered_by_llm': 0, 'uncovered': 2}

[c-002] non_compliant art 53   فترة التجربة المذكورة (180 يوماً) تتجاوز الحد النظامي ٩٠ يوماً
[c-004] non_compliant art 84   لا يجوز الاتفاق على إسقاط حق العامل في مكافأة نهاية الخدمة
[c-005] non_compliant art 98   ساعات العمل الأسبوعية (56) تتجاوز الحد النظامي ٤٨ ساعة
[c-006] non_compliant art 109  الإجازة السنوية (15 يوماً) أقل من الحد النظامي ٢١ يوماً
[c-007] risky         art 60   الإنهاء دون إشعار قد يكون تعسفياً ما لم يثبت سبب مشروع
```

Note `c-002`: the contract says "ستة أشهر" in words, and the rule engine converts
that to 180 days before comparing against the 90-day statutory maximum. Word-form
durations are the common case in real Arabic contracts.

## 6. Report downloads

```
docx: 38,248 bytes
html: 7,502 bytes
```

Both are generated from the stored analysis, so the report can be re-downloaded
later without re-running the model. The Word document uses right-to-left
paragraph directions so it renders correctly in Word.

Committed examples: [sample-contract-audit.docx](samples/sample-contract-audit.docx) ·
[sample-contract-audit.html](samples/sample-contract-audit.html), generated from
[sample-contract.txt](samples/sample-contract.txt).

## 7. Usage stats

```
queries: 3  refused: 2  avg latency: 8.7ms
```

Every question is logged with its verification outcome, latency and cost — that
is the audit trail, and it is also how you notice a retrieval regression before
a user does.

---

## What the demo does *not* prove

The corpus is synthetic and tiny. These numbers demonstrate that the machinery
works and the invariants hold (no unverified citations, no ungrounded answers,
refusals where evidence is missing). They say nothing about legal accuracy, which
requires the real corpus and a much larger gold set — see
[MVP.md](MVP.md) and the roadmap in the [README](../README.md).

## Troubleshooting

| Symptom | Cause |
|---|---|
| `cannot reach http://127.0.0.1:8080` | server not running, or a different `--port` |
| `chunks: 0` | database empty — `python -m bayyinah ingest corpora/raw` |
| `501` on the docx link | `python-docx` not installed; HTML still works |
| `401` on `/api/stats` | `BAYYINAH_API_KEY` is set; pass `X-API-Key` |
