"""Report rendering: Markdown, standalone HTML, and DOCX.

A finding nobody can forward is a finding nobody uses. The report is a
first-class output because the buyer is an HR consultant who needs something to
hand a client, not a chat log.
"""

from __future__ import annotations

import html
from pathlib import Path

from ..schemas import XRayReport

VERDICT_LABEL = {
    "non_compliant": "مخالف",
    "risky": "مخاطرة",
    "compliant": "سليم",
    "not_covered": "غير مشمول",
}
VERDICT_ORDER = ["non_compliant", "risky", "compliant", "not_covered"]

DISCLAIMER = (
    "هذا التحليل آلي واسترشادي، ويعتمد على النصوص النظامية المحمّلة في النظام. "
    "ليس استشارة قانونية. راجع مختصاً قبل التنفيذ."
)


def to_markdown(report: XRayReport) -> str:
    counts = report.counts()
    lines = [
        f"# تحليل عقد — {report.filename}",
        "",
        f"**{counts.get('non_compliant', 0)} مخالف · "
        f"{counts.get('risky', 0)} مخاطرة · "
        f"{counts.get('compliant', 0)} سليم · "
        f"{counts.get('not_covered', 0)} غير مشمول**",
        "",
    ]
    for finding in report.findings:
        label = VERDICT_LABEL.get(finding.verdict, finding.verdict)
        head = f"### {finding.clause_id} — {label}"
        if finding.citation:
            head += f" (المادة {finding.citation.article_no})"
        lines.append(head)
        lines.append("")
        lines.append(f"> {finding.clause_text.strip()}")
        lines.append("")
        if finding.rationale:
            lines.append(f"- **السبب:** {finding.rationale}")
        if finding.suggested_redline:
            lines.append(f"- **الاقتراح:** {finding.suggested_redline}")
        if finding.citation and finding.citation.quote:
            lines.append(f"- **النص النظامي:** «{finding.citation.quote.strip()}»")
        lines.append("")
    if report.notes:
        lines.append("---")
        for note in report.notes:
            lines.append(f"- {note}")
        lines.append("")
    lines.append(f"> ⚠️ {DISCLAIMER}")
    return "\n".join(lines)


def to_html(report: XRayReport, *, title: str | None = None) -> str:
    counts = report.counts()
    rows = []
    for finding in report.findings:
        label = VERDICT_LABEL.get(finding.verdict, finding.verdict)
        cite = (
            f'<div class="cite"><b>المادة {html.escape(finding.citation.article_no)}</b>'
            f"<q>{html.escape(finding.citation.quote.strip())}</q></div>"
            if finding.citation
            else ""
        )
        rows.append(
            f'<article class="finding {finding.verdict}">'
            f'<header><span class="tag">{html.escape(label)}</span>'
            f'<span class="cid">{html.escape(finding.clause_id)}</span></header>'
            f'<blockquote>{html.escape(finding.clause_text.strip())}</blockquote>'
            + (f'<p><b>السبب:</b> {html.escape(finding.rationale)}</p>' if finding.rationale else "")
            + (
                f'<p class="fix"><b>الاقتراح:</b> {html.escape(finding.suggested_redline)}</p>'
                if finding.suggested_redline
                else ""
            )
            + cite
            + "</article>"
        )

    notes = "".join(f"<li>{html.escape(n)}</li>" for n in report.notes)
    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<title>{html.escape(title or report.filename)}</title>
<style>
  body{{font-family:"Segoe UI","Noto Naskh Arabic",Tahoma,sans-serif;max-width:820px;
       margin:40px auto;padding:0 20px;line-height:1.8;color:#14181d;background:#fff}}
  h1{{font-size:24px;border-bottom:3px solid #0b6b3a;padding-bottom:10px}}
  .summary{{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0 26px}}
  .summary span{{padding:4px 12px;border-radius:20px;background:#f1f3f4;font-size:13px}}
  .summary .bad{{background:#fdeceb;color:#b3261e}} .summary .warn{{background:#fff6e5;color:#8a5a00}}
  .finding{{border:1px solid #e3e6ea;border-inline-start:5px solid #b9c0c8;border-radius:8px;
           padding:14px 18px;margin-bottom:14px}}
  .finding.non_compliant{{border-inline-start-color:#b3261e}}
  .finding.risky{{border-inline-start-color:#d08b00}}
  .finding.compliant{{border-inline-start-color:#0b6b3a}}
  header{{display:flex;justify-content:space-between;font-size:12px;color:#5d6672}}
  blockquote{{margin:8px 0;padding-inline-start:12px;border-inline-start:3px solid #eceff1;color:#5d6672}}
  .cite{{background:#f7f9f8;border-radius:6px;padding:8px 12px;font-size:13px;margin-top:8px}}
  .cite q{{display:block;margin-top:4px;color:#5d6672}}
  .fix{{color:#0b6b3a}}
  .disc{{margin-top:30px;padding-top:14px;border-top:1px solid #e3e6ea;font-size:12px;color:#5d6672}}
  @media print{{body{{margin:0}} .finding{{break-inside:avoid}}}}
</style></head><body>
<h1>تحليل عقد — {html.escape(report.filename)}</h1>
<div class="summary">
  <span class="bad">{counts.get('non_compliant', 0)} مخالف</span>
  <span class="warn">{counts.get('risky', 0)} مخاطرة</span>
  <span>{counts.get('compliant', 0)} سليم</span>
  <span>{counts.get('not_covered', 0)} غير مشمول</span>
</div>
{''.join(rows)}
<ul style="font-size:13px;color:#5d6672">{notes}</ul>
<div class="disc">⚠️ {html.escape(DISCLAIMER)}</div>
</body></html>"""


def to_docx(report: XRayReport, target) -> object:
    """Write a Word document to a path or a binary stream.

    python-docx is optional; callers should fall back to HTML when it is absent.
    """
    try:
        from docx import Document  # type: ignore
        from docx.oxml import OxmlElement  # type: ignore
        from docx.shared import Pt  # type: ignore
    except ImportError as exc:
        raise RuntimeError("DOCX export needs python-docx: pip install python-docx") from exc

    doc = Document()

    def rtl(paragraph) -> None:
        pPr = paragraph._p.get_or_add_pPr()
        bidi = OxmlElement("w:bidi")
        pPr.append(bidi)
        for run in paragraph.runs:
            rPr = run._element.get_or_add_rPr()
            rtl_el = OxmlElement("w:rtl")
            rPr.append(rtl_el)

    title = doc.add_heading(f"تحليل عقد — {report.filename}", level=1)
    rtl(title)

    counts = report.counts()
    summary = doc.add_paragraph(
        f"{counts.get('non_compliant', 0)} مخالف · {counts.get('risky', 0)} مخاطرة · "
        f"{counts.get('compliant', 0)} سليم · {counts.get('not_covered', 0)} غير مشمول"
    )
    rtl(summary)

    for finding in report.findings:
        label = VERDICT_LABEL.get(finding.verdict, finding.verdict)
        heading = doc.add_heading(
            f"{finding.clause_id} — {label}"
            + (f" (المادة {finding.citation.article_no})" if finding.citation else ""),
            level=2,
        )
        rtl(heading)

        clause = doc.add_paragraph(finding.clause_text.strip())
        clause.runs[0].italic = True
        rtl(clause)

        if finding.rationale:
            p = doc.add_paragraph(f"السبب: {finding.rationale}")
            rtl(p)
        if finding.suggested_redline:
            p = doc.add_paragraph(f"الاقتراح: {finding.suggested_redline}")
            rtl(p)
        if finding.citation and finding.citation.quote:
            p = doc.add_paragraph(f"النص النظامي: «{finding.citation.quote.strip()}»")
            rtl(p)
            for run in p.runs:
                run.font.size = Pt(9)

    note = doc.add_paragraph(DISCLAIMER)
    rtl(note)
    for run in note.runs:
        run.font.size = Pt(8)

    if hasattr(target, "write"):
        doc.save(target)
        return target
    out = Path(target)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))
    return out
