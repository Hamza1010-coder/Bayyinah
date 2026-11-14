"""Verify that relative links in Markdown files resolve.

Broken links are the first thing a reviewer notices on a repo landing page and
the last thing anyone checks. Run this in CI.

    python scripts/check_links.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
SKIP_PREFIX = ("http://", "https://", "mailto:", "#")


def check() -> list[tuple[Path, str]]:
    broken: list[tuple[Path, str]] = []
    for md in ROOT.rglob("*.md"):
        if any(part in {".git", "node_modules", "var"} for part in md.parts):
            continue
        text = md.read_text(encoding="utf-8")
        for target in LINK.findall(text):
            target = target.strip().split("#")[0].split(" ")[0]
            if not target or target.startswith(SKIP_PREFIX):
                continue
            resolved = (md.parent / target).resolve()
            if not resolved.exists():
                broken.append((md.relative_to(ROOT), target))
    return broken


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    broken = check()
    if not broken:
        print("all relative links resolve")
        return 0
    print(f"{len(broken)} broken link(s):")
    for source, target in broken:
        print(f"  {source} -> {target}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
