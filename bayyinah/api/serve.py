"""Server entry point.

    python -m bayyinah.api.serve              # http://127.0.0.1:8080
    python -m bayyinah.api.serve --port 9000 --seed

If the database is empty, the bundled corpus is ingested automatically so the
first run is not an empty page.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from ..config import REPO_ROOT, Settings
from .app import App, BayyinahServer

log = logging.getLogger("bayyinah")


def build_app(settings: Settings | None = None, *, db_path: str | Path | None = None) -> App:
    settings = settings or Settings.from_env()
    if db_path is not None:
        settings = Settings(**{**settings.__dict__, "db_path": Path(db_path)})
    app = App(settings)
    if len(app.corpus) == 0:
        seed(app)
    return app


def seed(app: App) -> None:
    raw = REPO_ROOT / "corpora" / "raw"
    if not raw.exists():
        return
    log.info("empty corpus — ingesting %s", raw)
    results = app.ingest_path(raw)
    for r in results:
        log.info("  %(filename)s: %(status)s (%(chunks)s chunks)", r)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bayyinah serve")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--db", default=None, help="path to sqlite database")
    ap.add_argument("--seed", action="store_true", help="(re)ingest corpora/raw on start")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    app = build_app(db_path=args.db)
    if args.seed:
        seed(app)

    server = BayyinahServer((args.host, args.port), app)
    synthetic = any(c.synthetic for c in app.corpus.chunks)
    print(f"Bayyinah on http://{args.host}:{args.port}")
    print(f"  chunks={len(app.corpus)}  documents={len(app.db.documents())}  model={app.llm.name}")
    if synthetic:
        print("  !! synthetic corpus — engineering tests only, not legal text", file=sys.stderr)
    if not app.settings.auth_enabled:
        print("  !! no BAYYYINAH_API_KEY set — API is unauthenticated (dev mode)", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
