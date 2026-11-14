"""Import the official statute from a saved web page or plain text.

The Bureau of Experts publishes the Labor Law as a web compilation. Saving that
page and running this importer is the fastest legitimate path to a real corpus:

    # in a browser, open the law page and Ctrl+S -> "Webpage, HTML only"
    python scripts/import_law.py saved.html --out corpora/raw/labor_law.txt
    python -m bayyinah ingest corpora/raw

The compilation wraps every article heading in editorial chrome ("معدلة — المرسوم
الملكي رقم…", "هل هناك خطأ؟ أبلغنا"). That chrome must not reach the vector store:
it pollutes quotes and, worse, makes the citation verifier's substring checks
pass on text that is not law.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from ..text.chunker import split_articles

BLOCK_TAGS = {
    "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "header", "footer", "table", "ul", "ol",
}

NOISE_LINE = re.compile(
    r"^\s*(?:"
    r"هل هناك خطأ.*|أبلغنا|"
    r"معدلة\s*—.*|مضافة\s*—.*|محذوفة\s*—.*|مادة محذوفة.*|"
    r"\(روجعت.*|\[↗.*|"
    r"هذه المادة\s*\*?\*?حُذفت.*|"
    r"شارك|طباعة|أضف إلى مكتبتي|نبّهني عند تحديثه|"
    r"سجّل الدخول.*|للعضوية المدفوعة"
    r")\s*$"
)

INLINE_NOISE = re.compile(
    r"\s*(?:هل هناك خطأ؟?\s*أبلغنا|أبلغنا|معدلة\s*—[^\n]*|مضافة\s*—[^\n]*|"
    r"محذوفة\s*—[^\n]*|\(روجعت يدويًّا\)|\[↗[^\]]*\])"
)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript", "nav"}:
            self._skip += 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "nav"} and self._skip:
            self._skip -= 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


@dataclass
class ImportReport:
    articles: int = 0
    first: str | None = None
    last: str | None = None
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "articles": self.articles,
            "first": self.first,
            "last": self.last,
            "missing": self.missing,
            "warnings": self.warnings,
        }


def strip_html(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return "".join(parser.parts)


def clean(text: str) -> str:
    """Remove editorial chrome, keep the law."""
    text = INLINE_NOISE.sub("", text)
    lines = []
    for line in text.splitlines():
        if NOISE_LINE.match(line):
            continue
        lines.append(line.rstrip())
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def import_bytes(raw: bytes, filename: str) -> tuple[str, ImportReport]:
    payload = raw.decode("utf-8", errors="replace")
    text = strip_html(payload) if filename.lower().endswith((".html", ".htm")) else payload
    text = clean(text)

    report = ImportReport()
    articles = split_articles(text)
    report.articles = len(articles)
    if articles:
        report.first = articles[0][0]
        report.last = articles[-1][0]

    numbers = []
    for number, _ in articles:
        if number.isdigit():
            numbers.append(int(number))
    if numbers:
        expected = set(range(min(numbers), max(numbers) + 1))
        report.missing = [str(n) for n in sorted(expected - set(numbers))][:20]

    if report.articles < 50:
        report.warnings.append(
            f"only {report.articles} articles found — the statute has 252. "
            "If you saved the page from a browser, make sure you saved the whole "
            "document (Ctrl+S while the page is fully loaded), not a print preview."
        )
    if not articles:
        report.warnings.append(
            "no article headings matched. Expected lines like 'المادة الثانية والعشرون'."
        )

    # Re-emit with a canonical heading line so downstream chunking is stable
    # regardless of what the source page looked like.
    canonical = "\n\n".join(f"المادة {number}\n{body}" for number, body in articles)
    return canonical or text, report
