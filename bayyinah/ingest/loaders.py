"""Document loaders.

Support matrix, honestly stated:

| Format | Path | Notes |
|---|---|---|
| .txt / .md | stdlib | primary path for legislation |
| .docx | python-docx | paragraphs + tables; most contracts arrive here |
| .html | stdlib HTMLParser | scraped pages |
| .pdf | pypdf (optional) | text-layer PDFs only |

Everything works on **bytes**, not temp files: uploads are never written to disk,
which removes a whole class of "where did that file go" problems and a data
retention question we would rather not have.

Arabic PDFs are almost always image-based or use embedded fonts without a
Unicode map, which yields mojibake. That is an OCR problem, not a parsing
problem, and pretending otherwise produces confidently wrong quotes. The loader
raises with an actionable message instead of returning garbage.
"""

from __future__ import annotations

import html
import io
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

SUPPORTED = {".txt", ".md", ".markdown", ".docx", ".html", ".htm", ".pdf"}


class LoaderError(RuntimeError):
    pass


@dataclass
class LoadedDoc:
    text: str
    filename: str
    kind: str
    pages: int = 0
    warnings: list[str] = field(default_factory=list)


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1256", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


class _TextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "nav", "footer"}:
            self._skip += 1
        elif tag in {"p", "div", "br", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "nav", "footer"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self.parts.append(data)


def _load_docx(raw: bytes, filename: str) -> LoadedDoc:
    try:
        import docx  # type: ignore
    except ImportError as exc:
        raise LoaderError("DOCX support needs python-docx:  pip install python-docx") from exc

    document = docx.Document(io.BytesIO(raw))
    parts = [p.text for p in document.paragraphs if p.text and p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text and c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    text = "\n".join(parts)
    if not text.strip():
        raise LoaderError(f"{filename}: no extractable text (image-only document?)")
    return LoadedDoc(text=text, filename=filename, kind="docx")


def _load_pdf(raw: bytes, filename: str) -> LoadedDoc:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:
        raise LoaderError(
            "PDF support needs pypdf:  pip install pypdf\n"
            "For scanned or Arabic PDFs you additionally need OCR "
            "(e.g. ocrmypdf with the Arabic language pack). "
            "Converting to .txt or .docx is usually faster."
        ) from exc

    reader = PdfReader(io.BytesIO(raw))
    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - one bad page must not kill the document
            pages.append("")
    text = "\n".join(pages)
    warnings: list[str] = []

    if len(text.strip()) < 40:
        raise LoaderError(
            f"{filename}: almost no text extracted — this is a scanned PDF. "
            "Run OCR first (ocrmypdf --language ara) or supply a .txt/.docx."
        )
    letters = re.findall(r"[\u0600-\u06FFA-Za-z]", text)
    if len(letters) < len(text) * 0.2:
        warnings.append(
            "low letter ratio — likely a broken font map or an Arabic PDF without "
            "a Unicode layer. Verify the extracted text before trusting quotes."
        )
    return LoadedDoc(text=text, filename=filename, kind="pdf", pages=len(pages), warnings=warnings)


def _load_html(raw: bytes, filename: str) -> LoadedDoc:
    parser = _TextHTMLParser()
    parser.feed(_decode(raw))
    text = html.unescape("".join(parser.parts))
    text = re.sub(r"\n{3,}", "\n\n", text)
    if not text.strip():
        raise LoaderError(f"{filename}: no text found in HTML")
    return LoadedDoc(text=text, filename=filename, kind="html")


def load_bytes(raw: bytes, filename: str) -> LoadedDoc:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED:
        raise LoaderError(
            f"unsupported format {suffix!r}. Supported: {', '.join(sorted(SUPPORTED))}"
        )
    if suffix == ".docx":
        return _load_docx(raw, filename)
    if suffix == ".pdf":
        return _load_pdf(raw, filename)
    if suffix in {".html", ".htm"}:
        return _load_html(raw, filename)
    text = _decode(raw)
    if not text.strip():
        raise LoaderError(f"{filename}: empty file")
    return LoadedDoc(text=text, filename=filename, kind="text")


def load(path: str | Path) -> LoadedDoc:
    p = Path(path)
    if not p.exists():
        raise LoaderError(f"file not found: {p}")
    if p.is_dir():
        raise LoaderError(f"{p} is a directory — use ingest_directory()")
    return load_bytes(p.read_bytes(), p.name)
