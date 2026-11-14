"""Citation verification.

The whole product rests on this file. A prompt that says "cite your sources"
is not a control; a function that fails the answer when the quote is not a
substring of the source is a control.

Hard failures  -> answer is regenerated once, then downgraded to sources-only.
Soft failures  -> recorded, shown in the audit log, do not block.
"""

from __future__ import annotations

import re

from ..schemas import Answer, VerificationProblem
from ..text.normalize import normalize_for_match

MIN_QUOTE_WORDS = 4
# "للمادة 84" and "المادة (٨٤)" must both match, so do not require the
# definite article: 'مادة' is a substring of every inflected form.
ARTICLE_REF = re.compile(r"ماد[ةه]\s*[\(\[]?\s*([0-9]{1,3})", re.IGNORECASE)


def _resolve(store, citation) -> object | None:
    if citation.doc_id:
        found = store.get_article(citation.doc_id, citation.article_no)
        if found:
            return found
    # Fall back to article number alone across the corpus.
    for chunk in store.chunks:
        if str(chunk.article_no) == str(citation.article_no):
            return chunk
    return None


def verify(answer: Answer, store) -> list[VerificationProblem]:
    problems: list[VerificationProblem] = []

    for citation in answer.citations:
        chunk = _resolve(store, citation)
        if chunk is None:
            problems.append(
                VerificationProblem(
                    kind="article_not_found",
                    severity="hard",
                    detail=f"Article {citation.article_no} does not exist in the corpus.",
                    citation=citation.to_dict(),
                )
            )
            continue

        if not citation.quote.strip():
            problems.append(
                VerificationProblem(
                    kind="empty_quote",
                    severity="hard",
                    detail=f"Citation to article {citation.article_no} has no quote.",
                    citation=citation.to_dict(),
                )
            )
            continue

        if normalize_for_match(citation.quote) not in normalize_for_match(chunk.text_display):
            problems.append(
                VerificationProblem(
                    kind="quote_not_verbatim",
                    severity="hard",
                    detail=(
                        f"Quote attributed to article {citation.article_no} is not a "
                        "verbatim substring of the source text."
                    ),
                    citation=citation.to_dict(),
                )
            )
            continue

        if len(normalize_for_match(citation.quote).split()) < MIN_QUOTE_WORDS:
            problems.append(
                VerificationProblem(
                    kind="quote_too_short",
                    severity="soft",
                    detail="Quote is too short to be meaningful evidence on its own.",
                    citation=citation.to_dict(),
                )
            )

    # Every article number named in the prose must be cited.
    cited = {str(c.article_no) for c in answer.citations}
    named = set(ARTICLE_REF.findall(normalize_for_match(answer.answer_ar or "")))
    for art in named - cited:
        problems.append(
            VerificationProblem(
                kind="uncited_article_reference",
                severity="soft",
                detail=f"Answer references article {art} without citing it.",
            )
        )

    return problems


def has_hard_failure(problems: list[VerificationProblem]) -> bool:
    return any(p.severity == "hard" for p in problems)


def summarize(problems: list[VerificationProblem]) -> list[str]:
    return [f"{p.kind}: {p.detail}" for p in problems]
