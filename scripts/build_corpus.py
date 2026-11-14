"""Deprecated shim: the corpus now lives in SQLite, ingest via the CLI.

    python -m bayyinah ingest corpora/raw
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from bayyinah.cli import main  # noqa: E402


def run() -> int:
    print("scripts/build_corpus.py is deprecated; ingesting into SQLite instead.\n")
    return main(["ingest", str(ROOT / "corpora" / "raw")])


if __name__ == "__main__":
    raise SystemExit(run())
