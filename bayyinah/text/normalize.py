"""Arabic text normalization.

Two *different* normalizers exist here on purpose, and mixing them up is the
single most common bug in Arabic RAG systems:

``normalize_for_index``  -- aggressive. Removes information to maximize recall.
                            Safe: only ever applied to the retrieval copy.

``normalize_for_match``  -- conservative. Used by the citation verifier to check
                            that a quoted span really appears in the source.
                            It must NOT change letters, because doing so can
                            make a paraphrased quote look verbatim.

Rule of thumb: if you are comparing text to text for verification, use
``normalize_for_match`` on both sides. If you are building a search key, use
``normalize_for_index``.
"""

from __future__ import annotations

import re
import unicodedata

# Harakat, tanween, shadda, sukun, superscript alef, Quranic marks.
DIACRITICS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")
TATWEEL = re.compile(r"\u0640+")
# Arabic punctuation lives INSIDE the 0600-06FF block, so a naive
# [^\w\s\u0600-\u06FF] filter happily leaves "؟" glued to the token. It has to
# be stripped explicitly or it poisons both the index and BM25 terms.
ARABIC_PUNCT = re.compile(r"[\u060C\u061B\u061F\u066A-\u066D\u06D4\u00AB\u00BB\u2018\u2019\u201C\u201D]")
PUNCT = re.compile(r"[^\w\s\u0600-\u06FF]+", re.UNICODE)
WHITESPACE = re.compile(r"\s+")

STOPWORDS = {
    "ما", "هي", "هو", "هم", "في", "من", "على", "الى", "عن", "هذا", "هذه",
    "ذلك", "تلك", "هل", "كم", "او", "ثم", "قد", "كان", "كانت", "يكون",
    "التي", "الذي", "الذين", "كل", "بعد", "قبل", "عند", "بين", "حتى",
    "اذا", "لا", "لم", "لن", "ان", "يا", "بل", "لكن", "كما", "لدى",
    "مع", "اي", "هنا", "هناك", "له", "لها", "به", "بها", "عليه", "عليها",
    "ايضا", "فقط", "غير", "سوف", "كيف", "متى", "اين", "لماذا", "ماذا",
}

ARABIC_INDIC = "٠١٢٣٤٥٦٧٨٩"
EXTENDED_ARABIC_INDIC = "۰۱۲۳۴۵۶۷۸۹"
ASCII_DIGITS = "0123456789"
_DIGIT_MAP = {
    **{ord(a): d for a, d in zip(ARABIC_INDIC, ASCII_DIGITS)},
    **{ord(a): d for a, d in zip(EXTENDED_ARABIC_INDIC, ASCII_DIGITS)},
}

ALEF_FORMS = {"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا"}
HAMZA_FORMS = {"ؤ": "و", "ئ": "ي", "ى": "ي"}


def strip_diacritics(text: str) -> str:
    return DIACRITICS.sub("", text)


def unify_digits(text: str) -> str:
    """Convert Arabic-Indic and Extended Arabic-Indic digits to ASCII.

    Users type ٩٠ and 90 interchangeably, and the law uses (٩٠). Retrieval and
    any numeric comparison happen on ASCII; display text keeps the original.
    """
    return text.translate(_DIGIT_MAP)


def unify_letters(text: str, *, ta_marbuta: bool = False) -> str:
    for src, dst in ALEF_FORMS.items():
        text = text.replace(src, dst)
    for src, dst in HAMZA_FORMS.items():
        text = text.replace(src, dst)
    if ta_marbuta:
        text = text.replace("ة", "ه")
    return text


def _base(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = strip_diacritics(text)
    text = TATWEEL.sub("", text)
    text = unify_digits(text)
    text = ARABIC_PUNCT.sub(" ", text)
    return text


def _strip_lam_article(token: str) -> str:
    """Drop the definite article so 'الاجازة' matches 'إجازة'.

    Without this, "ال" alone kills recall: it is attached to roughly a third of
    the words in formal Arabic, and BM25 treats 'الاجازه' and 'اجازه' as
    unrelated terms.
    """
    if len(token) > 4 and token.startswith("ال"):
        return token[2:]
    return token


def _light_stem(token: str) -> str:
    """Crude but effective Arabic light stemming.

    'ساعة' and 'ساعات' are the same concept; 'مكافأة' and 'مكافآت' are the same
    concept. Without at least plural/feminine folding, half the vocabulary
    silently fails to match and recall collapses on real user phrasing.

    Rules are intentionally conservative: apply to the index only, never to
    display text, and never touch the citation verifier's comparison.
    """
    if len(token) >= 4 and token.endswith("ات"):  # مكافآت -> مكاف
        return token[:-2]
    if len(token) >= 4 and token.endswith(("ون", "ين")):
        return token[:-2]
    if len(token) >= 5 and token.endswith("اه"):  # مكافأة -> مكاف
        return token[:-2]
    if len(token) >= 4 and token.endswith("ه") and not token.endswith("اه"):
        return token[:-1]
    return token


def normalize_for_index(text: str) -> str:
    """Aggressive normalization for the search key. Never display this."""
    text = _base(text)
    text = unify_letters(text, ta_marbuta=True)
    text = PUNCT.sub(" ", text)
    tokens = [
        _light_stem(_strip_lam_article(t))
        for t in WHITESPACE.sub(" ", text).strip().lower().split(" ")
    ]
    return " ".join(t for t in tokens if t)


def content_tokens(text: str) -> list[str]:
    """Index tokens minus stopwords and one/two-letter noise.

    Retrieval scoring must use these, not raw tokens: a question containing
    "ما هي ... في" otherwise scores 2/9 overlap against an irrelevant article
    purely on stopwords.
    """
    return [t for t in tokenize(text) if len(t) > 2 and t not in STOPWORDS]


def normalize_for_match(text: str) -> str:
    """Conservative normalization for citation verification.

    Keeps letter identity intact (no ta-marbuta folding) so that a genuine
    paraphrase cannot be mistaken for a verbatim quote.
    """
    text = _base(text)
    text = unify_letters(text, ta_marbuta=False)
    text = PUNCT.sub(" ", text)
    return WHITESPACE.sub(" ", text).strip()


def tokenize(text: str) -> list[str]:
    return [t for t in normalize_for_index(text).split(" ") if t]


def char_ngrams(text: str, n: int = 3) -> list[str]:
    """Character n-grams over the normalized key, word-boundary padded.

    Arabic is morphologically rich; char n-grams recover inflection that word
    matching misses ("المكافأة" vs "مكافاة").
    """
    norm = normalize_for_index(text).replace(" ", "_")
    if len(norm) < n:
        return [norm] if norm else []
    return [norm[i : i + n] for i in range(len(norm) - n + 1)]


def contains_normalized(haystack: str, needle: str) -> bool:
    """True if `needle` appears in `haystack` after conservative normalization."""
    h = normalize_for_match(haystack)
    n = normalize_for_match(needle)
    return bool(n) and n in h
