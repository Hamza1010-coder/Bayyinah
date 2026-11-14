"""Bayyinah — Arabic-first, citation-grounded compliance copilot.

Core is stdlib-only by design: `python -m bayyinah.api.serve` works on a
fresh machine with no virtualenv, no GPU, no network.
"""

__version__ = "0.1.0"

SYNTHETIC_WARNING = (
    "The bundled corpus in corpora/fixtures is SYNTHETIC and for engineering "
    "tests only. Replace it with the official published texts before demoing "
    "to anyone who might act on the output."
)
