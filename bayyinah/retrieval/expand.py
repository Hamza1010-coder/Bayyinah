"""Query expansion for the lexical path.

Legal Arabic and HR Arabic are different registers. A user writes
"لو استقلت بعد ست سنوات كم آخذ؟"; the statute says "ترك العامل العمل بمحض
إرادته". A lexical retriever sees no overlap and refuses a question it should
answer.

This is a stopgap, and it is labelled as one. A real embedding model (BGE-M3)
bridges the gap semantically and makes most of these rules unnecessary. Rules
are kept because they are free, deterministic, and auditable -- and because
they let the zero-dependency demo retrieve correctly.
"""

from __future__ import annotations

import re

# (pattern, expansion, reason)
RULES: list[tuple[re.Pattern[str], str, str]] = [
    (
        re.compile(r"استقل|أستقيل|استقال|استقيل|أستقيل"),
        " ترك العمل بمحض إرادته ",
        "resignation is phrased as 'ترك العمل بمحض إرادته' in the statute",
    ),
    (
        re.compile(r"صرف(?:وني|ني)|طرد|مفصول"),
        " فصل العامل ",
        "colloquial dismissal vs statutory 'فصل'",
    ),
    (
        re.compile(r"نهاية الخدمة|مكافأة"),
        " مكافأة نهاية الخدمة ",
        "pin the full statutory term",
    ),
]


def expand_query(question: str) -> str:
    additions = [text for pattern, text, _ in RULES if pattern.search(question)]
    if not additions:
        return question
    return question + " " + " ".join(a.strip() for a in additions)


def explain(question: str) -> list[str]:
    """Which expansions fired, for the audit log."""
    return [reason for pattern, _, reason in RULES if pattern.search(question)]
