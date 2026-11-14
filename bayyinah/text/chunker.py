"""Article-aware chunking.

Legal text must be chunked structurally. A fixed 512-token window sliced out of
the Labor Law produces chunks that start mid-sentence and lose the article
number -- which is precisely the unit users want to cite. So: split on
``المادة``, keep the number, and only sub-split articles that are themselves
too long.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Iterable

from .normalize import normalize_for_index, normalize_for_match, unify_digits
from .arabic_numbers import parse_number_with_end

# Article headings appear in three shapes in real corpora:
#
#   المادة 84            digits (synthetic fixtures, translations)
#   المادة (٨٤)          Arabic-Indic digits in brackets
#   المادة الثانية والعشرون   words -- how the official statute numbers articles
#
# The word form is the one that matters. Capturing the rest of the line and
# parsing it covers all three with one rule.
ARTICLE_HEADING = re.compile(r"(?:^|\n)[ \t]*(?:المادة|الماده)[ \t]+([^\n]{1,80})")
ARTICLE_EN = re.compile(r"(?:^|\n)\s*Article\s+(\d{1,3})\b", re.IGNORECASE)

# If the text after the heading is longer than this, the article body starts on
# the same line ("المادة 84: يستحق العامل ...").
INLINE_BODY_MIN = 25

SENTENCE_SPLIT = re.compile(r"(?<=[.؟!:؛])\s+|\n{2,}")

DEFAULT_MAX_CHARS = 1800
DEFAULT_OVERLAP_CHARS = 250


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    article_no: str
    chapter: str
    page: int
    lang: str
    text_display: str      # untouched text -- the verifier quotes from this
    text_norm: str         # search key
    url: str = ""
    synthetic: bool = False
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Chunk":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


def _canonical_article(raw: str) -> str:
    """'٨٤' -> '84'. Article numbers are compared as ASCII strings."""
    return unify_digits(raw).strip()


def _article_marks(text: str) -> list[tuple[int, int, str]]:
    """Locate article boundaries as (heading_start, body_start, article_no)."""
    marks: list[tuple[int, int, str]] = []
    seen: dict[str, int] = {}

    for match in ARTICLE_HEADING.finditer(text):
        number, consumed = parse_number_with_end(match.group(1))
        if number is None:
            continue  # "المادة التي تنظم ..." is prose, not a heading

        number_end = match.start(1) + consumed
        line_end = text.find("\n", number_end)
        if line_end == -1:
            line_end = len(text)

        remainder = text[number_end:line_end].strip(" \t:،-–")
        body_start = number_end if len(remainder) >= INLINE_BODY_MIN else line_end

        article_no = str(number)
        if article_no in seen:  # "المادة الحادية عشرة (مكرر)"
            seen[article_no] += 1
            article_no = f"{article_no}م{seen[article_no] - 1}"
        else:
            seen[article_no] = 1

        marks.append((match.start(), body_start, article_no))

    if not marks:  # no Arabic headings at all -> try an English translation
        for match in ARTICLE_EN.finditer(text):
            line_end = text.find("\n", match.start())
            marks.append((match.start(), match.end(), match.group(1)))

    return marks


def split_articles(text: str) -> list[tuple[str, str]]:
    """Split a statute into [(article_no, body), ...] in document order."""
    ordered = _article_marks(text)
    if not ordered:
        return [("0", text.strip())]

    ordered.sort(key=lambda m: m[0])
    out: list[tuple[str, str]] = []
    for i, (_, body_start, number) in enumerate(ordered):
        stop = ordered[i + 1][0] if i + 1 < len(ordered) else len(text)
        body = text[body_start:stop].strip(" \t:،-–\n")
        if body:
            out.append((number, body))
    return out


def split_long(body: str, max_chars: int, overlap_chars: int) -> list[str]:
    """Split one article body on sentence boundaries, keeping overlap."""
    if len(body) <= max_chars:
        return [body]
    sentences = [s for s in SENTENCE_SPLIT.split(body) if s and s.strip()]
    if not sentences:
        return [body[i : i + max_chars] for i in range(0, len(body), max_chars)]
    pieces: list[str] = []
    current: list[str] = []
    size = 0
    for s in sentences:
        if size + len(s) > max_chars and current:
            pieces.append(" ".join(current))
            tail = " ".join(current)[-overlap_chars:]
            current = [tail] if tail else []
            size = len(tail)
        current.append(s)
        size += len(s) + 1
    if current:
        pieces.append(" ".join(current))
    return pieces


def chunk_document(
    text: str,
    *,
    doc_id: str,
    lang: str = "ar",
    title: str = "",
    chapter: str = "",
    url: str = "",
    page_of: dict[str, int] | None = None,
    synthetic: bool = False,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for article_no, body in split_articles(text):
        for part_i, part in enumerate(split_long(body, max_chars, overlap_chars)):
            # The heading is prepended to the *search key* only. This measurably
            # helps "which article says..." queries without polluting quotes.
            header = f"{title} {chapter}".strip()
            chunk = Chunk(
                chunk_id=f"{doc_id}:{article_no}:{part_i}",
                doc_id=doc_id,
                article_no=article_no,
                chapter=chapter,
                page=(page_of or {}).get(article_no, 0),
                lang=lang,
                text_display=part,
                text_norm=normalize_for_index(f"{header} المادة {article_no} {part}"),
                url=url,
                synthetic=synthetic,
            )
            chunks.append(chunk)
    return chunks


def dedupe(chunks: Iterable[Chunk]) -> list[Chunk]:
    seen: set[str] = set()
    out: list[Chunk] = []
    for c in chunks:
        key = normalize_for_match(c.text_display)[:200]
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out
