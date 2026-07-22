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

**The gaps this note tracked are closed; do not read that as "the set is closed".**
#396 wrote "not every porcelain emitter is gated", #406 closed three ``result`` rows and
said so, and #416 closed the eleven this paragraph then listed. What is measured today:
every caller-influenced field on a positional row under ``factlog/`` reaches
:func:`porcelain_field`. Every bare ``print(f"…\\t…")`` that remains interpolates an
``int``, a ``len()`` or a ``'0'``/``'1'`` literal — a count cannot carry a tab.

What #416 closed, with the evidence for each, because the two strengths were not equal:

* Both ``query`` rows (``arxiv-search``, ``pubmed-search``) — the user's own ``--query``,
  the most caller-influenced value on any row here. **Measured:** ``--query $'a\\tb'
  --show-query --porcelain`` emitted ``query\\ta\\tb``, three columns against a contract
  of two.
* All five ``target`` rows — a path built from the user's ``--target``, and a POSIX
  filename may hold a tab or a newline outright. **Measured, all five**, by putting the
  KB in a directory whose name carries the character. #406 left four of these five at
  grep strength and said so; running them settled it in the direction the note feared.
* Three of the four dry-run ``item``/``work`` rows — the fourth, ``_pubmed_finish``'s, was
  already gated by #141, which is why this shape existed four times with one checked.
  **Measured for three of the four:** a tab-carrying Zotero key, a tab-carrying versioned
  arXiv id from the client response, and — through that pubmed sibling — a tab-carrying
  PMID from a real efetch body, which arrives and is neutralized to a space, so the gate
  is doing visible work rather than guarding an unreachable path. The OpenAlex one is the
  exception and is **not measured**: ``openalex-import`` rejects a response id that is
  not ``W<digits>``, and a hostile title is slugified before it reaches the filename
  column, so no route was found that carries a tab there. It is gated regardless —
  ``outcome.key`` *is* ``work.openalex_id``, the same value ``_openalex_show_results``
  gates one row over, and a caller gates its value rather than reasoning about what its
  own parser admits.
* The ``candidate`` row (``_candidate_porcelain_lines``, #75). **Measured**, through the
  real importer. This one is worth its own sentence: it was **not in the list #406 wrote**,
  and it was found by re-running the grep this paragraph tells you to run rather than by
  trusting the list. The note's own advice caught the note's own omission.

Line numbers are deliberately absent now. Every earlier revision carried them, every
revision's numbers went stale within a merge or two, and the last one was stale on
arrival — so the instruction is the durable part: **grep the bare ``print(f"`` rows
before trusting any claim here, including this one.** That instruction has earned itself
twice: once when the ``target`` group turned up after this paragraph claimed five
emitters, and once when the ``candidate`` row turned up after it claimed ten.

The tense matters. This paragraph is in the past tense because the holes it names are
shut, and #406's revision was rewritten into the past tense while ten were still open,
which quietly invited a reader to mistake an ungated path for a checked one. If you open
a new emitter, add it here in the present tense and say which strength of evidence you
have — "measured" and "grep" are different claims and #416 kept them apart on purpose.

Note what kind of gap those were, because this module has seen both kinds. The ones above
were **ungated** — no neutralization at all. The three ``*-backfill-provenance`` commands
were something worse to review: **stale, not ungated**. Each kept its own local copy of
the tab/CR/LF rule, which *looked* checked while silently falling behind when #396 widened
the shared set, so eight characters it now neutralizes still split those rows in two. They
were converted to call this function (#396). A near-copy does not stay correct by being
correct once, which is the whole argument for one definition; an obvious gap at least
announces itself — provided a note like this one keeps announcing it.
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

    **What is deliberately NOT neutralized**, and why that is a decision about the two
    contracts rather than about any one caller's input: a control character that adds
    neither a column nor a row is left alone. It can only look odd, and stripping it would
    put this function in the business of deciding what renders nicely — the "all
    human-readable output" scope both contracts above exclude.

    Two such characters are known to reach here, by different routes, and neither is
    universal — this function has several consumers and they do not share a parser:

    * **U+007F DEL** reaches the #396 warning gate through a real PubMed efetch
      (measured); XML 1.0 admits it and ``work_parser._text`` does not collapse it,
      since it is not Python whitespace.
    * **ESC** is *not* reachable through that XML path — XML 1.0 rejects it outright —
      but it very much is elsewhere: JSON admits it (``json.loads('"a\\u001bb"')`` →
      ``'a\\x1bb'``), so an OpenAlex ``reason`` can carry one, and a POSIX filename may
      contain it outright, so a ``ledger`` path can too. A row carrying ``\\x1b[2K``
      (ANSI erase-line) was emitted through this gate and still measured three fields on
      one line. It is left alone for the same reason DEL is: a terminal may erase what is
      already drawn, but the row's field count and line count — all either contract
      claims — are untouched.

    Do not read either bullet as "this gate is narrow enough". Both are notes about what
    happens to reach it today, from parsers this function does not control and callers it
    has not met; a caller gates its value rather than reasoning about what its own parser
    admits (the error #396's first cut shipped, in the opposite direction).
    """
    return text.translate(_NEUTRALIZE)
