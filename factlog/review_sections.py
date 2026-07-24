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

A section is an **ATX ``## `` heading**. Not any ``#`` line: a ``## 출처 부족``
inside a fenced code block was being taken for the section itself, and a bullet
routed to it landed after the closing fence, in no section at all. ``## `` is also
what ``merge_candidates.insert_bullet`` scans for when it looks for where a section
ends, so the two agree on what a boundary is. A Setext heading (``출처`` over
``----``) is not recognised; the reference documents that.

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

TITLE = "# Open Questions"

# What `factlog init` writes, and what the producer starts from when the file does
# not exist. Deliberately no placeholder bullets: validate.py reads "a needs_review
# row exists but there are no review bullets" as an error, and a "- 현재 없음." in
# the scaffold would answer that check for every KB forever.
OPEN_QUESTIONS_SCAFFOLD = (
    TITLE + "\n\n" + "\n\n".join(heading for _, heading in REVIEW_CATEGORIES) + "\n"
)


def _headings(text: str) -> list[str]:
    """The ``## `` section headings of *text*, raw (trailing whitespace included).

    Raw because the caller feeds the result to ``merge_candidates.insert_bullet``,
    which locates a section by exact line equality.

    Two narrowings, both measured against the same failure. ``## `` exactly and
    unindented, which is the test ``insert_bullet`` uses to find where a section
    *ends*; and nothing inside a fenced code block, because a ``## 출처 부족``
    written as an example in a fence was read as the section itself — the file
    reported no missing sections while having no real 출처 section, and a bullet
    routed there was inserted after the closing fence, in no section at all.

    ``insert_bullet``'s own end-of-section scan does not know about fences, so a
    bullet in a section that embeds a fenced ``## `` example stops at the fence
    rather than at the section's end. That is a placement wart inside one section,
    not a bullet lost between two, and #104 owns that scan.
    """
    headings: list[str] = []
    fenced = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fenced = not fenced
            continue
        if not fenced and line.startswith("## "):
            headings.append(line)
    return headings


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
    """
    missing = missing_review_sections(text)
    if not missing:
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
