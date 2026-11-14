"""Command line interface.

    python -m bayyinah ingest corpora/raw
    python -m bayyinah ask "كم مدة فترة التجربة؟"
    python -m bayyinah serve --port 8080
    python -m bayyinah docs
    python -m bayyinah stats
    python -m bayyinah export --out report.docx   (needs a contract id)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .config import REPO_ROOT, Settings
from .db import Database
from .generation.render import render_markdown


def _app(db_path: str | None = None):
    from .api.serve import build_app

    return build_app(db_path=db_path)


def cmd_ingest(args: argparse.Namespace) -> int:
    app = _app(args.db)
    target = Path(args.path)
    if not target.exists():
        print(f"not found: {target}", file=sys.stderr)
        return 2
    results = app.ingest_path(target)
    for r in results:
        status = r["status"]
        marker = {"created": "+", "updated": "~", "unchanged": "=", "failed": "!"}[status]
        print(f"{marker} {r['filename']:<40} {status:<9} {r['chunks']:>3} chunks")
        for warning in r["warnings"]:
            print(f"    ! {warning}")
        if r["error"]:
            print(f"    ! {r['error']}", file=sys.stderr)
    failed = sum(1 for r in results if r["status"] == "failed")
    print(f"\n{len(app.corpus)} chunks total across {len(app.db.documents())} documents")
    return 1 if failed else 0


def cmd_ask(args: argparse.Namespace) -> int:
    app = _app(args.db)
    result = app.answer_service.ask(args.question)
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(render_markdown(result.answer))
        print(f"\n[{result.latency_ms} ms · {result.model} · ${result.cost_usd:.4f} · query #{result.query_id}]")
    return 0


def cmd_docs(args: argparse.Namespace) -> int:
    app = _app(args.db)
    rows = app.db.documents()
    if not rows:
        print("no documents ingested yet")
        return 0
    print(f"{'doc_id':<32} {'chunks':>6}  {'lang':<4} {'title'}")
    print("-" * 78)
    for row in rows:
        flag = " (synthetic)" if row["synthetic"] else ""
        print(f"{row['doc_id']:<32} {row['n_chunks']:>6}  {row['lang']:<4} {row['title']}{flag}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    app = _app(args.db)
    from .services import stats

    print(json.dumps(stats(app.db), ensure_ascii=False, indent=2))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .api import serve

    argv = ["--host", args.host, "--port", str(args.port)]
    if args.db:
        argv += ["--db", args.db]
    return serve.main(argv)


def cmd_reset(args: argparse.Namespace) -> int:
    if not args.yes:
        print("this deletes all documents, queries and reports. pass --yes", file=sys.stderr)
        return 2
    db = Database(args.db or Settings.from_env().db_path)
    db.reset()
    print("database reset")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    script = REPO_ROOT / "evals" / "run_eval.py"
    cmd = [sys.executable, str(script)]
    if args.fail_on_gate:
        cmd.append("--fail-on-gate")
    return subprocess.call(cmd, cwd=str(REPO_ROOT))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="bayyinah", description="Arabic-first compliance copilot")
    ap.add_argument("--db", default=None, help="sqlite database path")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ingest", help="ingest a file or directory")
    p.add_argument("path")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("ask", help="ask one question")
    p.add_argument("question")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("docs", help="list ingested documents")
    p.set_defaults(func=cmd_docs)

    p = sub.add_parser("stats", help="usage statistics")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("serve", help="run the web app")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("eval", help="run the eval harness")
    p.add_argument("--fail-on-gate", action="store_true")
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("reset", help="delete all data (dangerous)")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_reset)
    return ap


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
