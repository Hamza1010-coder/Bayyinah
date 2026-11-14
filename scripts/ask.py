"""Deprecated shim: ask one question.

    python -m bayyinah ask "كم مدة فترة التجربة؟"
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from bayyinah.cli import main  # noqa: E402

if __name__ == "__main__":
    args = sys.argv[1:]
    raise SystemExit(main(["ask", *args] if args else ["ask", "ما هي فترة التجربة القصوى؟"]))
