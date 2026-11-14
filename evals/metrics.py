"""Eval metrics. Small, explicit, no framework.

Every function takes plain data and returns a float. That is deliberate: a
metric you cannot read in 30 seconds is a metric you will not trust, and an
eval you do not trust will be deleted in month two.
"""

from __future__ import annotations

from typing import Iterable, Sequence


def safe_div(num: float, den: float) -> float:
    return num / den if den else 0.0


def recall_at_k(gold_articles: Sequence[str], retrieved: Sequence[str], k: int) -> float:
    """1.0 if any gold article is in the top-k."""
    gold = {str(g) for g in gold_articles}
    top = {str(a) for a in retrieved[:k]}
    return 1.0 if gold & top else 0.0


def mrr(gold_articles: Sequence[str], retrieved: Sequence[str]) -> float:
    gold = {str(g) for g in gold_articles}
    for rank, art in enumerate(retrieved, start=1):
        if str(art) in gold:
            return 1.0 / rank
    return 0.0


def precision_at_k(gold_articles: Sequence[str], retrieved: Sequence[str], k: int) -> float:
    gold = {str(g) for g in gold_articles}
    top = [str(a) for a in retrieved[:k]]
    return safe_div(sum(1 for a in top if a in gold), len(top))


def citation_precision(cited: Sequence[str], gold_articles: Sequence[str]) -> float:
    """Share of cited articles that are relevant -- penalises padding citations."""
    gold = {str(g) for g in gold_articles}
    return safe_div(sum(1 for c in cited if str(c) in gold), len(cited))


def rate(flags: Iterable[bool]) -> float:
    flags = list(flags)
    return safe_div(sum(1 for f in flags if f), len(flags))


def mean(values: Iterable[float]) -> float:
    values = list(values)
    return safe_div(sum(values), len(values))
