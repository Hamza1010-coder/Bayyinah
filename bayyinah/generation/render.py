"""Rendering an Answer to something a human can forward."""

from __future__ import annotations

from ..schemas import Answer
from .pipeline import DISCLAIMER_AR


def render_markdown(answer: Answer, *, show_disclaimer: bool = True) -> str:
    lines: list[str] = []

    if answer.refusal:
        lines.append(f"**{answer.refusal}**")
        if answer.refusal_reason == "out_of_scope":
            lines.append("")
            lines.append("_النطاق: نظام العمل السعودي فقط._")
        lines.append("")
    elif answer.answer_ar:
        lines.append(answer.answer_ar)
        lines.append("")

    for calc in answer.calculations:
        lines.append(f"**الاحتساب** ({calc.formula_ref})")
        for step in calc.trace:
            lines.append(f"- {step}")
        lines.append(f"- **المستحق: {calc.result:,.2f} {calc.unit}**")
        lines.append("")

    if answer.citations:
        lines.append("**المصادر**")
        for i, c in enumerate(answer.citations, start=1):
            ref = f"المادة {c.article_no}"
            if c.doc_id:
                ref = f"{c.doc_id} — {ref}"
            lines.append(f"[{i}] {ref}")
            if c.quote:
                lines.append(f"    «{c.quote.strip()}»")
        lines.append("")

    if answer.requires_human_review:
        lines.append("⚖️ _تحتاج هذه الحالة إلى مراجعة مختص قبل التنفيذ._")
        lines.append("")

    if answer.confidence:
        lines.append(f"_درجة الثقة: {answer.confidence}_")

    if show_disclaimer:
        lines.append("")
        lines.append(f"⚠️ {DISCLAIMER_AR}")

    return "\n".join(lines).strip()


def render_sources_plain(answer: Answer) -> str:
    return "\n".join(f"- المادة {c.article_no}" for c in answer.citations)
