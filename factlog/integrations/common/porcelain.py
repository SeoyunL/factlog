# SPDX-License-Identifier: Apache-2.0
"""The one neutralization rule every ``--porcelain`` row shares (issue #141).

A porcelain row is a tab-separated positional contract (#78): a fixed number of
fields, read by column offset. Any caller-influenced value in a row — a source or
corrupt-ledger *path* in an id column, an ``OSError`` message that carries a path in a
``reason``, a list of sidecar paths — can hold a tab and add a column, or a line break
and split the row; either way a positional consumer reads the wrong field, silently.

The arXiv and OpenAlex integrations both emit such rows, so the rule lives here rather
than hand-mirrored in each (#111 added it to OpenAlex's ``reason`` alone, and arXiv had
no such helper at all until #141 wrote one). One definition keeps "both integrations'
porcelain emits the documented field count" from quietly splitting in two.

Porcelain named the rule; it is not the only place that needs it. A stderr warning whose
*block shape* carries meaning breaks the same way — see :func:`porcelain_field` on the
second contract (#396) — and such a caller reuses this rule rather than growing a near-copy
under a second name, which is how the two integrations drifted apart in the first place.

**Not every porcelain emitter is gated yet.** ``_pubmed_show_results`` and
``_arxiv_show_results`` (``cli.py``) print their ``result`` rows with bare f-strings, so
the *first* contract above is open in the two search commands — every other porcelain
emitter in the tree goes through this function. Out of scope for #396, which fixed the
warning path in the same command; recorded here so the gap is not mistaken for a checked
path. (Issue number to follow.)
"""
from __future__ import annotations


# Tab (adds a column) plus every character `str.splitlines()` treats as a line break.
# That list, not "the C0 range", is the right generator: what breaks both contracts is
# line-splitting, and three of these — U+0085 NEL, U+2028, U+2029 — are NOT C0 and are
# perfectly legal XML 1.0 (measured: `&#133;`/`&#8232;`/`&#8233;` parse fine where
# `&#27;` is a parse error). Gating on "control character" would have missed exactly
# those three, which is the hole #396's first cut shipped with.
_LINE_BREAKS = ("\n", "\v", "\f", "\r", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029")
_NEUTRALIZE = {ord(char): " " for char in ("\t", *_LINE_BREAKS)}


def porcelain_field(text: str) -> str:
    """Replace every tab and line break in ``text`` with a single space each.

    Each such character maps to one space, so ``"\\r\\n"`` becomes two spaces. That is
    deliberate: the guarantee is that no tab and no line break survives — never that the
    field's length is preserved — so a row keeps its field count and stays a single line.

    Two contracts rest on that one guarantee, and neither is "all human-readable output".
    The first is the positional one above: a porcelain row read by column offset. The
    second is a **human** line whose shape is itself load-bearing — ``pubmed-search``'s
    year-range warning is one line of claim plus one indented continuation, so a line
    break inside a quoted ``MedlineDate`` splits the block and lets record data appear as
    a ``⚠`` line of factlog's own (#396). Prose that merely *contains* a caller value is
    still left untouched; what earns the gate is output where the character changes how
    the reader parses the line, not merely how it looks.

    **What is deliberately NOT neutralized.** A non-line-breaking control character —
    U+007F DEL is the reachable one, and it reaches the #396 gate through a real efetch
    today (measured) — is left alone. It cannot add a column or a row, so it breaks
    neither contract; it can only look odd. Stripping it would put this function in the
    business of deciding what renders nicely, which is the "all human-readable output"
    scope both contracts above are written to exclude. ESC, the one that could forge a
    line by moving a terminal's cursor, is not reachable: XML 1.0 rejects it outright.

    That last fact is a reason this gate need not grow, never a reason it may be skipped
    — the caller's job is to gate the value, not to prove which characters its parser
    happens to admit today.
    """
    return text.translate(_NEUTRALIZE)
