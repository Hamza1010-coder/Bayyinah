"""Arabic number words, for article headings.

The published Labor Law numbers its articles in words:

    المادة الأولى            المادة الثانية والعشرون
    المادة الحادية عشرة      المادة المائة والثانية والعشرون

A chunker that only accepts digits (`المادة 84`) silently produces one giant
"article 0" for the entire statute — which is what happened the first time this
repo was pointed at real text. Worse, the failure is quiet: retrieval still
returns *something*.

The grammar is compositional and additive: units add to tens add to hundreds.
"الحادية والعشرون" = 1 + 20 = 21. "المائة والثانية والخمسون" = 100 + 2 + 50.
"""

from __future__ import annotations

import re

UNITS = {
    "الأول": 1, "الأولى": 1, "الحادي": 1, "الحادية": 1,
    "الثاني": 2, "الثانية": 2,
    "الثالث": 3, "الثالثة": 3,
    "الرابع": 4, "الرابعة": 4,
    "الخامس": 5, "الخامسة": 5,
    "السادس": 6, "السادسة": 6,
    "السابع": 7, "السابعة": 7,
    "الثامن": 8, "الثامنة": 8,
    "التاسع": 9, "التاسعة": 9,
    "العاشر": 10, "العاشرة": 10,
    # Bare form used in compound teens: "الحادية عشرة" = 1 + 10.
    "عشرة": 10, "عشر": 10,
}

TENS = {
    "العشرون": 20, "العشرين": 20,
    "الثلاثون": 30, "الثلاثين": 30,
    "الأربعون": 40, "الأربعين": 40,
    "الخمسون": 50, "الخمسين": 50,
    "الستون": 60, "الستين": 60,
    "السبعون": 70, "السبعين": 70,
    "الثمانون": 80, "الثمانين": 80,
    "التسعون": 90, "التسعين": 90,
}

HUNDREDS = {
    "المائة": 100, "مائة": 100, "المئة": 100, "مئة": 100,
    "المائتان": 200, "مائتان": 200, "المئتان": 200,
    "الثلاثمائة": 300, "ثلاثمائة": 300, "الثلاثمئة": 300,
    "الأربعمائة": 400, "أربعمائة": 400,
}

VOCAB = {**UNITS, **TENS, **HUNDREDS}

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

# Words that end the article number and begin something else (amendment badges).
STOP_WORDS = {"معدلة", "مضافة", "محذوفة", "مكرر", "هل", "أبلغنا", "روجعت"}

NOISE = re.compile(
    r"\s*(?:هل هناك خطأ.*|أبلغنا|معدلة\s*—.*|مضافة\s*—.*|محذوفة\s*—.*|"
    r"مادة محذوفة.*|\(روجعت.*|\[↗.*)$"
)

_TOKEN = re.compile(r"[\u0600-\u06FF0-9]+")

# Amendment badges are glued straight onto the heading: "الثانية عشرةمعدلة — …".
# Truncating before tokenizing is more reliable than trying to strip afterwards.
_CUT = re.compile(r"(?:معدلة|مضافة|محذوفة|مكرر|هل هناك|أبلغنا|روجعت|\[↗)")


def _value(token: str) -> int | None:
    token = token.strip()
    if not token:
        return None
    if token.startswith("و") and len(token) > 2:
        token = token[1:]
    if token in VOCAB:
        return VOCAB[token]
    digits = token.translate(ARABIC_DIGITS)
    if digits.isdigit():
        return int(digits)
    return None


def parse_number(text: str) -> int | None:
    """Parse a numeral written either as digits or as Arabic words.

    Returns None when the text is not a number at all, which is the signal the
    chunker uses to decide "this is not an article heading".
    """
    return parse_number_with_end(text)[0]


def parse_number_with_end(text: str) -> tuple[int | None, int]:
    """Same, plus the offset just past the consumed numerals.

    The offset is what lets the chunker tell a heading line from an inline body:
    "المادة 84: يستحق العامل …" must keep the text after the 84.
    """
    text = NOISE.sub("", text.strip())
    cut = _CUT.search(text)
    if cut:
        text = text[: cut.start()]
    tokens = list(_TOKEN.finditer(text))
    if not tokens:
        return None, 0

    total = 0
    consumed = 0
    end = 0
    for match in tokens:
        token = match.group(0)
        if token in STOP_WORDS:
            break
        value = _value(token)
        if value is None:
            # A non-numeric word before any numeral means this is prose, not a
            # heading ("المادة التي تنظم ...").
            if consumed == 0:
                return None, 0
            break
        total += value
        consumed += 1
        end = match.end()

    return (total, end) if consumed else (None, 0)

