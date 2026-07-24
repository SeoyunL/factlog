# SPDX-License-Identifier: Apache-2.0
"""The four review sections of ``decisions/open-questions.md``, in one place.

This module is the **single source of truth for the review-section contract**:
which categories a KB's open-questions file keeps, what a freshly scaffolded one
looks like, which heading a new bullet belongs under, and which categories a file
is missing. Producer (``tools/merge_candidates.py``), scaffolder
(:mod:`factlog.cli`) and validator (``tools/validate.py``) all read the answer
from here instead of restating it.

The extraction is #495. The three of them had each hardcoded their own version of
the same four categories and the copies did not agree:

- the validator asked for ``중복``/``모호``/``출처``/``충돌`` **anywhere in the
  document**, so a heading was never actually required — a bullet that happened to
  contain the word satisfied it;
- the producer wrote ``## 중복 개념 후보`` / ``## 모호한 관계명`` / ``## 출처 부족``
  / ``## 기존 내용과 충돌할 수 있는 항목`` and passed the validator only because
  those names happen to contain its substrings;
- ``write_decisions`` created the file as ``# Open Questions`` and nothing else, so
  a KB scaffolded by ``init`` could never reach rc=0 down the normal path.

The cost was not theoretical. A KB whose four sections had been written by hand
under *different* names ended up with each category split in two: the hand-written
headings at the top saying "현재 없음" while the producer's headings, hundreds of
lines below, held the actual review queue. Both the validator and a human skimming
the top of the file reported that there was nothing to review.

So the two operations have to agree, and that is the point of this module:
:func:`ensure_review_sections` only adds a heading for a category that has **no**
heading yet, and :func:`section_for` sends a bullet to whichever heading that
category already has. Scaffolding and bullet placement read the same list, so a
file whose headings are spelled differently keeps them and no *new* second section
is opened for a category that already had one.

That is the whole of it, and it is worth being exact about the limit: **a file
already split across two headings per category is not repaired here.** Both
functions stop at the first heading they find, so new bullets move to the earlier
section and the later one keeps whatever it accumulated — the split survives, only
its direction changes. Merging them is a rewrite of a document a human wrote, which
is theirs to make, so this module says so out loud instead
(:func:`split_review_sections`, surfaced as a validator warning) and leaves it.

A section is an **ATX ``## `` heading outside any code fence**. Not any ``#`` line,
and not a line in a fence: a ``## 출처 부족`` written as an example was taken for
the section itself, and the bullet routed to it landed past the closing fence, in
no section at all. A Setext heading (``출처`` over ``----``) is not recognised; the
reference documents that, and nothing here improves it (#500).

**Every reader and writer of the file takes those definitions from here.** Four
questions used to be answered by scans of their own, none of them aware of fences.
Each was found by measuring, one round after another, and each had let the file and
the report about the file disagree:

* *where does a section start* — ``insert_bullet``'s ``lines.index``, which matched
  a heading inside a fence and filed the bullet under no section at all
  (:func:`section_line_index`);
* *where does it end* — its own ``startswith("## ")`` walk, which stopped at a
  fenced example and inserted into the code block (:func:`section_end_index`);
* *have I filed this bullet, and is anything filed here* — the producer's whole-file
  line comparison and the validator's ``- `` count, which between them made a
  needs_review row vanish from the file a human reads while the KB reported
  completely valid (:func:`review_bullets`);
* *is this stale-source record already written* — a substring test over the whole
  document, answered just as well by an example in a fence (:func:`review_bullets`).

A second notion of where a section is, disagreeing with this one, is what #495 was
about to begin with.

The one file shape nothing writes to is one that **ends inside an unclosed fence**
(:func:`ends_inside_fence`). Appending happens at the end of the file, and there the
end is inside the fence: headings written there cannot be read back, bullets written
there never render, and the next pass sees the same categories missing and appends
again. The writers stop and say so instead, naming the line
(:func:`unclosed_fence_line`), because closing the fence is a human's edit.

**Anything added here has to be a claim about which sections the file keeps.**
What a bullet says, when a row deserves review, and whether a human has decided
are not that claim.
"""
from __future__ import annotations

# (keyword, canonical heading) in the order a scaffolded file lists them.
#
# The keyword is what identifies the category in a heading that already exists —
# it is deliberately short, because existing KBs qualify their headings
# ("## 중복 (Duplicate Review)", "## 중복 (같은 개념의 다른 이름)") and all of those
# spellings are the same category. The canonical heading is only used when a file
# has no heading for the category at all.
REVIEW_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("중복", "## 중복 개념 후보"),
    ("모호", "## 모호한 관계명"),
    ("출처", "## 출처 부족"),
    ("충돌", "## 기존 내용과 충돌할 수 있는 항목"),
)

# The keyword set on its own, for callers that route by category and want a drift in
# REVIEW_CATEGORIES to be loud at import rather than at the first row they classify.
REVIEW_KEYWORDS: frozenset[str] = frozenset(keyword for keyword, _ in REVIEW_CATEGORIES)

TITLE = "# Open Questions"

# What `factlog init` writes, and what the producer starts from when the file does
# not exist. Deliberately no placeholder bullets: validate.py reads "a needs_review
# row exists but there are no review bullets" as an error, and a "- 현재 없음." in
# the scaffold would answer that check for every KB forever.
OPEN_QUESTIONS_SCAFFOLD = (
    TITLE + "\n\n" + "\n\n".join(heading for _, heading in REVIEW_CATEGORIES) + "\n"
)


# CommonMark lets a fence marker carry up to three leading spaces; at four it is an
# indented code block, i.e. ordinary content that opens nothing. Counting those as
# fences made a well-formed document read as permanently unclosed.
_MAX_FENCE_INDENT = 3


def _scan_fences(text: str) -> tuple[list[bool], int | None]:
    """Per-line "is this inside a code fence", and where an unclosed fence opened.

    One scan, one answer, used by everything below. It used to be written out twice
    — once to find headings and once to ask whether the file ended mid-fence — and
    two copies of the rule for what a section is are what #495 was about in the
    first place.

    Opening and closing are a plain toggle. Matching the marker's character and
    length the way CommonMark does would only ever *reduce* what counts as fenced,
    and this scan errs toward "treat it as content" — the safe direction for a
    writer deciding whether to write, since the cost of being wrong is a heading or
    a bullet buried in a code block.
    """
    flags: list[bool] = []
    opened_at: int | None = None
    for index, line in enumerate(text.splitlines()):
        body = line.lstrip(" ")
        indent = len(line) - len(body)
        if indent <= _MAX_FENCE_INDENT and (
            body.startswith("```") or body.startswith("~~~")
        ):
            opened_at = None if opened_at is not None else index
            flags.append(True)
            continue
        flags.append(opened_at is not None)
    return flags, opened_at


def _headings(text: str) -> list[str]:
    """The ``## `` section headings of *text*, raw (trailing whitespace included).

    Raw because callers feed the result back to :func:`section_line_index`, which
    locates a section by exact line equality.

    ``## `` exactly, unindented, and outside any code fence. A ``## 출처 부족``
    written as an example inside a fence was read as the section itself: the file
    reported no missing sections while having no real 출처 section, and the bullet
    routed there was inserted after the closing fence, in no section at all.
    """
    lines = text.splitlines()
    flags, _ = _scan_fences(text)
    return [
        line
        for line, fenced in zip(lines, flags)
        if not fenced and line.startswith("## ")
    ]


def review_bullets(text: str) -> list[str]:
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
    flags, _ = _scan_fences(text)
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
    return _scan_fences(text)[1] is not None


def unclosed_fence_line(text: str) -> int | None:
    """The 1-based line number where an unclosed fence opened, or None.

    For telling an operator *where*. "This file has a review section missing" sends
    someone looking for a heading that is right there in front of them; "the fence
    on line 5 is never closed" is the same failure said in a way they can act on.
    """
    opened_at = _scan_fences(text)[1]
    return None if opened_at is None else opened_at + 1


def section_line_index(text: str, heading: str) -> int | None:
    """Where the section titled *heading* starts, or None if *text* has no such one.

    The lookup ``merge_candidates.insert_bullet`` uses. It used to be a plain
    ``lines.index(heading)``, which found the heading *inside a code fence* and filed
    the bullet against it — measured: the bullet landed just past the closing fence,
    under no section at all, and the run still exited 0. A fenced line is not a
    section here, so it must not be one there either.
    """
    flags, _ = _scan_fences(text)
    for index, (line, fenced) in enumerate(zip(text.splitlines(), flags)):
        if not fenced and line == heading:
            return index
    return None


def section_end_index(text: str, start: int) -> int:
    """The line index just past the section that starts at *start*.

    Where a new bullet goes. Ends at the next ``## `` heading — the real ones only,
    so a section that quotes a ``## `` example in a fence is not cut short at it —
    or at the end of the file.
    """
    lines = text.splitlines()
    flags, _ = _scan_fences(text)
    end = start + 1
    while end < len(lines) and not (not flags[end] and lines[end].startswith("## ")):
        end += 1
    return end


def _heading_with(text: str, keyword: str) -> str | None:
    """The first heading of *text* carrying *keyword*, or None.

    First, not last: when a category ended up with two headings, the earlier one is
    the one a human reads, so that is where the queue belongs.
    """
    for line in _headings(text):
        if keyword in line:
            return line
    return None


def missing_review_sections(text: str) -> list[str]:
    """Keywords of the review categories *text* has no heading for.

    Heading, not substring. The document-wide substring test this replaced was
    satisfied by any bullet mentioning the word, which is exactly how a file could
    lose a whole section without the validator noticing.
    """
    return [
        keyword
        for keyword, _ in REVIEW_CATEGORIES
        if _heading_with(text, keyword) is None
    ]


def split_review_sections(text: str) -> list[tuple[str, list[str]]]:
    """Categories of *text* carrying more than one heading, with those headings.

    A split is not an error and nothing here repairs it: joining two sections means
    moving bullets a human wrote and filed, and that decision is theirs. But it is
    the state this whole module exists because of, and until now nobody downstream
    could see it — the earlier section says "- 현재 없음." while the queue sits in
    the later one, and both a reader skimming the top and every check in
    tools/validate.py agree there is nothing to review.

    So: say it, once, where an operator will read it. Repairing it is one edit and
    they are the only ones who can make it.
    """
    split: list[tuple[str, list[str]]] = []
    headings = _headings(text)
    for keyword, _ in REVIEW_CATEGORIES:
        matches = [line for line in headings if keyword in line]
        if len(matches) > 1:
            split.append((keyword, matches))
    return split


def ensure_review_sections(text: str) -> str:
    """*text* with a canonical heading appended for every category it lacks.

    Categories that already have a heading — under any spelling — are left exactly
    as they are, so this is churn-free on an existing KB and idempotent: the second
    call finds nothing missing and returns *text* unchanged. A category that has two
    is left alone as well; see :func:`split_review_sections` for why.

    A canonical heading whose text also appears inside a code fence *is* still
    written: the fenced copy is an example, not a section, and no reader or writer
    treats it as one — :func:`section_line_index` skips it too, so the bullets go to
    the real heading this adds. Refusing to write it instead left the document
    permanently short a section with no way to earn it back.
    """
    missing = missing_review_sections(text)
    if not missing:
        return text
    # The one file this declines to touch. An unclosed fence swallows the end of the
    # file, which is exactly where this appends — every heading written there would
    # land inside the fence, unreadable by the scan that just asked for it, and the
    # appended headings would read as missing again on the next pass, so the file
    # grew by three headings per merge and never converged. Write nothing; the
    # writers in merge_candidates stop on the same condition and say why.
    if ends_inside_fence(text):
        return text
    canonical = dict(REVIEW_CATEGORIES)
    # `.strip()`, not `.rstrip("\n")`: a file holding only spaces and newlines is as
    # titleless as an empty one, and rstrip left it truthy — the sections were then
    # appended under no title at all.
    body = text.rstrip("\n") if text.strip() else TITLE
    return "\n\n".join([body] + [canonical[keyword] for keyword in missing]) + "\n"


def section_for(text: str, keyword: str) -> str:
    """The heading in *text* a *keyword* bullet belongs under.

    The existing heading when there is one, so a bullet joins the section a reader
    already has rather than opening a second one beside it; the canonical heading
    otherwise.
    """
    existing = _heading_with(text, keyword)
    if existing is not None:
        return existing
    return dict(REVIEW_CATEGORIES)[keyword]
