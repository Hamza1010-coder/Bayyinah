"""End-to-end demo against a running server.

    python -m bayyinah serve          # terminal 1
    python scripts/demo.py            # terminal 2

Exercises every user-facing path and prints a transcript you can paste into a
README or read aloud in an interview.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SAMPLE_CONTRACT = """\
البند 1: يلتزم الطرف الثاني بالعمل لدى الطرف الأول بوظيفة أخصائي موارد بشرية.
البند 2: تكون فترة التجربة ستة أشهر قابلة للتمديد.
البند 3: تتقاضى الموظفة أجراً شهرياً قدره 9,500 ريال سعودي.
البند 4: يوافق الطرف الثاني على التنازل عن مكافأة نهاية الخدمة عند انتهاء العلاقة.
البند 5: تكون ساعات العمل 56 ساعة أسبوعياً.
البند 6: يستحق الموظف إجازة سنوية مدتها 15 يوماً.
البند 7: يجوز للطرف الأول إنهاء العقد دون إشعار في أي وقت."""


def call(base: str, path: str, payload: dict | None = None, method: str = "GET"):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json; charset=utf-8"} if data else {}
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read()
        ctype = resp.headers.get("Content-Type", "")
        if "json" in ctype:
            return json.loads(body.decode("utf-8"))
        return {"_bytes": len(body), "_type": ctype}


def hr(title: str) -> None:
    print(f"\n{'─' * 66}\n{title}\n{'─' * 66}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--json", action="store_true", help="dump raw responses")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    try:
        health = call(base, "/api/health")
    except (urllib.error.URLError, ConnectionError) as exc:
        print(f"cannot reach {base}: {exc}\nstart it with: python -m bayyinah serve", file=sys.stderr)
        return 2

    hr("1. health")
    print(f"  chunks       : {health['chunks']}")
    print(f"  documents    : {health['documents']}")
    print(f"  model        : {health['model']}")
    print(f"  synthetic    : {health['synthetic_corpus']}")
    print(f"  auth required: {health['auth_required']}")

    hr("2. grounded answer with a deterministic calculation")
    q = "كم مكافأة نهاية الخدمة إذا استقلت بعد 3 سنوات براتب 6000 ريال؟"
    print(f"  Q: {q}")
    r = call(base, "/api/ask", {"question": q}, "POST")
    a = r["answer"]
    print(f"  A: {a['answer_ar'][:110]}…")
    for calc in a["calculations"]:
        print(f"  calc ({calc['formula_ref']}):")
        for step in calc["trace"]:
            print(f"     {step}")
        print(f"     => {calc['result']:,.2f} {calc['unit']}")
    for c in a["citations"]:
        print(f"  cite: article {c['article_no']} | {c['quote'][:60]}…")
    print(f"  verified={not a['verification']} confidence={a['confidence']} "
          f"latency={r['latency_ms']}ms cost=${r['cost_usd']:.6f}")

    hr("3. refusal — foreign jurisdiction")
    q = "كم مدة الإشعار في قانون العمل الإماراتي؟"
    print(f"  Q: {q}")
    r = call(base, "/api/ask", {"question": q}, "POST")
    print(f"  refusal_reason: {r['answer']['refusal_reason']}")
    print(f"  citations     : {len(r['answer']['citations'])}")
    print(f"  text          : {r['answer']['refusal'][:90]}…")

    hr("4. refusal — no evidence in the corpus")
    q = "ما هي عقوبة عدم تسجيل العامل في التأمينات الاجتماعية؟"
    print(f"  Q: {q}")
    r = call(base, "/api/ask", {"question": q}, "POST")
    print(f"  refusal_reason: {r['answer']['refusal_reason']}")
    print(f"  citations     : {len(r['answer']['citations'])}")

    hr("5. contract X-Ray")
    r = call(base, "/api/contracts", {"text": SAMPLE_CONTRACT, "filename": "عقد_عمل.txt"}, "POST")
    counts = r["report"]["counts"]
    print(f"  {counts['non_compliant']} non-compliant · {counts['risky']} risky · "
          f"{counts['not_covered']} not covered")
    print(f"  coverage: {r['coverage']}")
    for f in r["report"]["findings"]:
        if f["verdict"] == "not_covered":
            continue
        art = f["citation"]["article_no"] if f["citation"] else "-"
        print(f"  [{f['clause_id']}] {f['verdict']:<13} art {art:<4} {f['rationale'][:60]}")

    hr("6. report downloads")
    docx = call(base, r["links"]["docx"])
    html = call(base, r["links"]["html"])
    print(f"  docx: {docx['_bytes']:,} bytes")
    print(f"  html: {html['_bytes']:,} bytes")

    hr("7. usage stats")
    s = call(base, "/api/stats")
    print(f"  queries: {s['queries']['total']}  refused: {s['queries']['refused']}  "
          f"avg latency: {s['queries']['avg_latency_ms']}ms")

    print("\nall endpoints exercised\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
