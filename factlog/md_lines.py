# SPDX-License-Identifier: Apache-2.0
"""What a markdown document's lines *are*, before anyone asks what they mean.

Which lines a renderer will show as code, where each heading begins and ends, and
which lines are list items. Four readers used to answer those questions with scans
of their own, none of them aware of fences, and each disagreement between the
copies let the file and the report about the file drift apart:

* *where does a section start* — ``insert_bullet``'s ``lines.index``, which matched
  a heading inside a fence and filed the bullet under no section at all;
* *where does it end* — its own ``startswith("## ")`` walk, which stopped at a
  fenced example and inserted into the code block (:func:`section_body_end`);
* *have I filed this bullet, and is anything filed here* — the producer's whole-file
  line comparison and the validator's ``- `` count, which between them made a
  needs_review row vanish from the file a human reads while the KB reported
  completely valid (:func:`bullets`);
* *is this stale-source record already written* — a substring test over the whole
  document, answered just as well by an example in a fence (:func:`bullets`).

A second notion of where a section is, disagreeing with this one, is what #495 was
about to begin with; #515 is the same lesson one level down — those four answers
had been living inside the module that owns the *review-category* contract, where
"is this line code" had to be read past to find "which categories does the file
keep".

**Anything added here has to be an answer a reader who does not know what the
document is for could still ask for** — which of its lines render as code, where
each heading starts and ends, which lines are list items. If a review category, a
file name, or a factlog concept has to be named to state the question, it is not
this module's: :mod:`factlog.review_sections` owns those.

Two things this deliberately does not claim:

* **Front matter is not read here.** A YAML block's closing ``---`` has exactly the
  shape of a Setext underline, and a naive scan calls every one of them a level-2
  heading — measured, 35 of them across one real KB's ``sources/*.md``. Nothing
  today feeds those files to this module, but a general module invites it, so:
  delimiting front matter is :mod:`factlog.front_matter_scan`'s, and a caller that
  wants both has to strip the block before asking here.
* **This is not a rendering library.** It answers the structural questions a
  producer and a validator have to agree on, and the fence and Setext rules exist
  for that reason rather than for their own sake.
"""
from __future__ import annotations

from dataclasses import dataclass

# CommonMark lets a fence marker carry up to three leading spaces; at four it is an
# indented code block, i.e. ordinary content that opens nothing. Counting those as
# fences made a well-formed document read as permanently unclosed.
_MAX_FENCE_INDENT = 3


def _fence_marker(line: str) -> tuple[str, int, str] | None:
    """*line* as a fence marker — ``(char, run length, rest)`` — or None.

    A run of three or more backticks or tildes, indented no more than
    :data:`_MAX_FENCE_INDENT`. ``rest`` is what follows the run, which decides
    whether the marker is allowed to close: an info string makes it an opener only.
    """
    body = line.lstrip(" ")
    if len(line) - len(body) > _MAX_FENCE_INDENT:
        return None
    for char in ("`", "~"):
        if body.startswith(char * 3):
            run = len(body) - len(body.lstrip(char))
            return char, run, body[run:]
    return None


def fence_flags(text: str) -> tuple[list[bool], int | None]:
    """Per-line "is this inside a code fence", and where an unclosed fence opened.

    One scan, one answer, used by everything below. It used to be written out twice
    — once to find headings and once to ask whether the file ended mid-fence — and
    two copies of the rule for what a section is are what #495 was about in the
    first place.

    A fence closes only on **CommonMark's terms**: the same character, a run at
    least as long as the opener's, and nothing after it but whitespace. Treating
    every marker as a plain toggle broke the one document this module's own
    reference recommends — a ``~~~`` block quoting a ```` ``` ```` line, which is
    how anyone writes a bullet-format example without nesting backticks. The
    backtick line "closed" the tilde fence and the real ``~~~`` re-opened it, so a
    correct file read as permanently unclosed and both writers refused it forever,
    pointing at the line that closes it and asking for it to be closed.

    Matching is not uniformly more or less strict than the toggle was: a
    non-matching marker no longer ends a fence (more of the file is code), and the
    marker that does match now ends it (less). What it is instead is **the same
    answer a renderer gives**, which is the only answer that matters — the whole
    point of the flag is whether a human will see the line or a code block.
    """
    flags: list[bool] = []
    opened_at: int | None = None
    open_marker: tuple[str, int] | None = None
    for index, line in enumerate(text.splitlines()):
        marker = _fence_marker(line)
        if marker is None:
            flags.append(opened_at is not None)
            continue
        char, run, rest = marker
        if open_marker is None:
            opened_at, open_marker = index, (char, run)
        elif char == open_marker[0] and run >= open_marker[1] and not rest.strip():
            opened_at, open_marker = None, None
        flags.append(True)
    return flags, opened_at


@dataclass(frozen=True)
class Heading:
    """A heading of the document, as a *place* rather than as a string.

    ``start`` is the index of its first line and ``end`` the index just past its
    last, so ``lines[start:end]`` is the heading and nothing else. ``text`` is those
    lines raw, joined by newlines, trailing whitespace and all: callers put it in
    warnings a human reads, and re-spelling it there would make the message disagree
    with the file.

    Why a place. Every caller that had a heading string went looking for it again
    with line equality — ``lines.index(heading)`` — and line equality answers "which
    line says this" rather than "where is the heading". The two differ whenever the
    body of a document repeats its own title line, and the caller then filed content
    against a line that is not a heading at all. Answering with the position once
    removes the second lookup, and with it the chance of a different answer.
    """

    start: int
    end: int
    level: int
    text: str


# A heading level of 7 does not exist; ``####### x`` is a paragraph.
_MAX_HEADING_LEVEL = 6


def _atx_level(line: str) -> int | None:
    """*line* as an unindented ATX heading — its level — or None.

    Unindented on purpose, which is narrower than CommonMark (it allows up to three
    leading spaces). This is the predicate the review-section scan has always used
    and widening it would move section boundaries in existing KBs, which is not what
    #500 is about; it is recorded here as a known narrowness rather than left to be
    rediscovered.
    """
    if not line.startswith("#"):
        return None
    run = len(line) - len(line.lstrip("#"))
    if run > _MAX_HEADING_LEVEL:
        return None
    # `#` and `## ` are headings; `###x` is not — the marker needs a space after it
    # or nothing at all.
    if len(line) > run and line[run] != " ":
        return None
    return run


def headings(text: str) -> list[Heading]:
    """Every heading of *text*, in document order, at **every** level.

    All levels, because "which levels count as a section" is a caller's contract and
    not a property of the document — :mod:`factlog.review_sections` keeps ``## ``
    and says so with a ``level == 2`` test, where it can be read and mutated. It used
    to be a ``startswith("## ")`` buried in the scan, where the contract was
    invisible from the module that owns it.

    Outside any code fence. A ``## 출처 부족`` written as an example inside a fence
    was read as the section itself: the file reported no missing sections while
    having no real 출처 section, and the bullet routed there was inserted after the
    closing fence, in no section at all.
    """
    lines = text.splitlines()
    flags, _ = fence_flags(text)
    found: list[Heading] = []
    for index, line in enumerate(lines):
        if flags[index]:
            continue
        level = _atx_level(line)
        if level is not None:
            found.append(Heading(start=index, end=index + 1, level=level, text=line))
    return found


def bullets(text: str) -> list[str]:
    """The bullet lines of *text* that are really bullets — raw, fences excluded.

    Who has already been filed, and whether anything has. Two places asked that and
    each answered it its own way, both counting lines inside code fences:
    ``insert_bullet`` deduplicated against them, so a bullet whose text was quoted as
    a *format example* in a fence was taken for already present and never written;
    and ``validate.py`` counted them, so that same example answered "this KB does have
    review bullets" for a file that had none. Together — measured — a needs_review row
    vanished from the file a human reads while the KB reported entirely valid.

    ``- `` after optional indentation, which is what a reader sees as a list item.
    """
    flags, _ = fence_flags(text)
    return [
        line
        for line, fenced in zip(text.splitlines(), flags)
        if not fenced and line.lstrip().startswith("- ")
    ]


def ends_inside_fence(text: str) -> bool:
    """Did *text* open a code fence and never close it?

    Everything after such a fence is content, including anything appended to the end
    of the file — so a writer that appends there is writing a heading it cannot read
    back, and a bullet no reader will ever see rendered. Ask before writing.
    """
    return fence_flags(text)[1] is not None


def unclosed_fence_line(text: str) -> int | None:
    """The 1-based line number where an unclosed fence opened, or None.

    For telling an operator *where*. "This file has a review section missing" sends
    someone looking for a heading that is right there in front of them; "the fence
    on line 5 is never closed" is the same failure said in a way they can act on.
    """
    opened_at = fence_flags(text)[1]
    return None if opened_at is None else opened_at + 1


def section_body_end(text: str, heading: Heading) -> int:
    """The line index just past the body of *heading* — where a new line goes.

    The body runs to the next heading at *heading*'s level or above, or to the end
    of the file. Level-aware because a section is ended by its peers and its
    parents, not by a subsection of its own: a ``### `` under a ``## `` is part of
    that section, and a ``# `` after it is not.

    Fence-aware for the same reason everything here is. The scan this replaced was
    ``startswith("## ")`` over the raw lines, which stopped at a ``## `` quoted as an
    example inside a fence and inserted the new bullet into the code block.
    """
    lines = text.splitlines()
    for other in headings(text):
        if other.start >= heading.end and other.level <= heading.level:
            return other.start
    return len(lines)
