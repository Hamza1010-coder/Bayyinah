"""Import a saved statute page into a clean corpus file.

    python scripts/import_law.py saved.html --out corpora/raw/labor_law.txt
    python -m bayyinah ingest corpora/raw
    python evals/run_eval.py --fail-on-gate

We do not download the page for you: the Bureau of Experts site requires a
browser, and silently scraping legislation is a good way to ingest a stale or
partial copy. Save it yourself, then convert it here with a report you can check.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from bayyinah.ingest.law_import import import_bytes  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="saved .html or .txt of the statute")
    ap.add_argument("--out", default="corpora/raw/labor_law.txt")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    src = Path(args.source)
    if not src.exists():
        print(f"not found: {src}", file=sys.stderr)
        return 2

    text, report = import_bytes(src.read_bytes(), src.name)
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"articles : {report.articles} ({report.first} … {report.last})")
        if report.missing:
            print(f"missing  : {', '.join(report.missing)}")
        for warning in report.warnings:
            print(f"warning  : {warning}", file=sys.stderr)
        print(f"written  : {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")

    return 0 if report.articles else 1


if __name__ == "__main__":
    raise SystemExit(main())
