# SPDX-License-Identifier: Apache-2.0
"""The review-section contract of decisions/open-questions.md (#495).

These are the pure half: what counts as having a section, what gets added to a
file that lacks one, and where a bullet for a category goes. The paths that
*apply* them — `factlog init` and tools/merge_candidates.py — are pinned in
tests/unit/test_open_questions_contract.py.

Two of the cases here are the bug itself rather than a hypothetical. The validator
used to look for the four keywords anywhere in the document, so a bullet that said
"출처" answered the check for the 출처 *section* — a file could lose the heading and
still pass. And the producer wrote a fixed heading per category, so a KB whose
headings were spelled differently grew a second section for a category it already
had, and the bullets went to the new one while the section a human reads stayed at
"현재 없음".
"""
from __future__ import annotations

import pytest

from factlog.review_sections import (
    OPEN_QUESTIONS_SCAFFOLD,
    REVIEW_CATEGORIES,
    ensure_review_sections,
    missing_review_sections,
    section_for,
    split_review_sections,
)

KEYWORDS = [keyword for keyword, _ in REVIEW_CATEGORIES]

# How an existing KB spells the four categories — neither of these matches the
# canonical headings, and both must be recognised as the same four sections.
SAMPLE_KB_HEADINGS = (
    "# Open Questions\n\n"
    "## 중복 (Duplicate Review)\n\n"
    "## 모호 (Ambiguity Review)\n\n"
    "## 출처 (Source Review)\n\n"
    "## 충돌 (Conflict Review)\n"
)
REAL_KB_HEADINGS = (
    "# Open Questions\n\n"
    "## 중복 (같은 개념의 다른 이름)\n\n"
    "## 모호 (관계명·개념 판단 필요)\n\n"
    "## 출처 (근거 강도 부족)\n\n"
    "## 충돌 (상충하는 후보)\n"
)


class TestMissingReviewSections:
    def test_the_scaffold_is_missing_nothing(self):
        assert missing_review_sections(OPEN_QUESTIONS_SCAFFOLD) == []

    def test_a_bare_title_is_missing_all_four(self):
        assert missing_review_sections("# Open Questions\n") == KEYWORDS

    def test_existing_kb_spellings_satisfy_every_category(self):
        # No churn: neither of these files may be reported as missing anything.
        assert missing_review_sections(SAMPLE_KB_HEADINGS) == []
        assert missing_review_sections(REAL_KB_HEADINGS) == []

    def test_a_bullet_mentioning_the_word_does_not_count_as_the_section(self):
        # The substring test this replaced passed on exactly this document.
        text = "# Open Questions\n\n- needs_review: 출처 부족한 후보 / 중복 / 모호 / 충돌\n"
        assert missing_review_sections(text) == KEYWORDS

    def test_a_heading_inside_a_code_fence_is_not_a_section(self):
        """Measured: the file below reported nothing missing and had no 출처 section.

        Worse than a false clean bill — section_for then answered with the fenced
        line, and merge_candidates inserted the bullet after the closing fence,
        between two sections and inside neither.
        """
        text = (
            "# Open Questions\n\n## 중복 개념 후보\n\n## 모호한 관계명\n\n"
            "예시:\n\n```\n## 출처 부족\n```\n\n"
            "## 기존 내용과 충돌할 수 있는 항목\n"
        )
        assert missing_review_sections(text) == ["출처"]
        assert section_for(text, "출처") == "## 출처 부족"  # canonical, not the fenced line

    def test_a_tilde_fence_hides_a_heading_too(self):
        text = "# Open Questions\n\n~~~\n## 출처 부족\n~~~\n"
        assert "출처" in missing_review_sections(text)

    def test_an_indented_heading_is_not_a_section(self):
        # Indented by four spaces is a code block, not a heading.
        text = "# Open Questions\n\n    ## 출처 부족\n"
        assert "출처" in missing_review_sections(text)

    def test_a_real_heading_after_a_closed_fence_still_counts(self):
        # The fence tracking must not swallow the rest of the document.
        text = "# Open Questions\n\n```\n## 중복 개념 후보\n```\n\n## 출처 부족\n"
        missing = missing_review_sections(text)
        assert "출처" not in missing
        assert "중복" in missing

    def test_every_category_is_reported_on_its_own(self):
        # Dropping a category from REVIEW_CATEGORIES has to be visible here, and a
        # file that lost exactly one heading must name exactly that one.
        assert len(KEYWORDS) == 4
        for keyword in KEYWORDS:
            without = "\n\n".join(
                heading for other, heading in REVIEW_CATEGORIES if other != keyword
            )
            assert missing_review_sections(f"# Open Questions\n\n{without}\n") == [keyword]


class TestEnsureReviewSections:
    def test_a_bare_title_gains_all_four_headings(self):
        out = ensure_review_sections("# Open Questions\n")
        assert missing_review_sections(out) == []
        for _, heading in REVIEW_CATEGORIES:
            assert any(line == heading for line in out.splitlines())

    def test_an_empty_file_gains_a_title_too(self):
        assert ensure_review_sections("") == OPEN_QUESTIONS_SCAFFOLD

    @pytest.mark.parametrize("blank", ["", "\n\n", "   \n\n", "\t\n", "  "])
    def test_a_file_of_only_whitespace_gains_a_title(self, blank):
        # `rstrip("\n") or TITLE` left "   " truthy, so the sections were appended
        # under no title at all.
        assert ensure_review_sections(blank) == OPEN_QUESTIONS_SCAFFOLD

    def test_existing_spellings_are_left_exactly_alone(self):
        # Churn-free on a real KB: no rewrite, and above all no second heading for
        # a category that already had one under another name.
        for text in (SAMPLE_KB_HEADINGS, REAL_KB_HEADINGS, OPEN_QUESTIONS_SCAFFOLD):
            assert ensure_review_sections(text) == text

    def test_only_the_missing_category_is_added(self):
        text = "# Open Questions\n\n## 중복 (Duplicate Review)\n- keep me\n"
        out = ensure_review_sections(text)
        assert out.startswith(text.rstrip("\n"))
        assert "- keep me" in out
        assert out.count("중복") == 1
        assert missing_review_sections(out) == []

    def test_it_is_idempotent(self):
        once = ensure_review_sections("# Open Questions\n")
        assert ensure_review_sections(once) == once
        twice = ensure_review_sections(ensure_review_sections(REAL_KB_HEADINGS))
        assert twice == REAL_KB_HEADINGS

    def test_no_placeholder_bullet_is_scaffolded(self):
        # A "- 현재 없음." here would permanently answer validate.py's "needs_review
        # rows exist but there are no review bullets" check.
        assert not [
            line
            for line in OPEN_QUESTIONS_SCAFFOLD.splitlines()
            if line.lstrip().startswith("- ")
        ]


class TestSplitReviewSections:
    """The state this module exists because of, reported rather than repaired."""

    def test_a_clean_file_reports_nothing(self):
        for text in (OPEN_QUESTIONS_SCAFFOLD, SAMPLE_KB_HEADINGS, REAL_KB_HEADINGS):
            assert split_review_sections(text) == []

    def test_the_real_kb_shape_is_reported(self):
        # What ~/factlog-kb looks like: four hand-written headings up top and the
        # producer's own headings further down, holding the actual queue.
        text = (
            REAL_KB_HEADINGS
            + "\n## 모호한 관계명\n- needs_review: a\n\n## 출처 부족\n- needs_review: b\n"
        )
        assert split_review_sections(text) == [
            ("모호", ["## 모호 (관계명·개념 판단 필요)", "## 모호한 관계명"]),
            ("출처", ["## 출처 (근거 강도 부족)", "## 출처 부족"]),
        ]

    def test_ensure_review_sections_does_not_repair_a_split(self):
        # Joining two sections moves bullets a human filed; that is their edit.
        text = REAL_KB_HEADINGS + "\n## 모호한 관계명\n- needs_review: a\n"
        assert ensure_review_sections(text) == text
        assert split_review_sections(text)


class TestSectionFor:
    def test_an_existing_heading_wins_over_the_canonical_one(self):
        for keyword, canonical in REVIEW_CATEGORIES:
            chosen = section_for(REAL_KB_HEADINGS, keyword)
            assert chosen != canonical
            assert chosen in REAL_KB_HEADINGS.splitlines()

    def test_the_canonical_heading_is_used_when_there_is_none(self):
        for keyword, canonical in REVIEW_CATEGORIES:
            assert section_for("# Open Questions\n", keyword) == canonical

    def test_the_first_of_two_headings_wins(self):
        # The split-section damage: the top heading is the one a human reads, so a
        # new bullet joins it rather than the duplicate further down.
        text = REAL_KB_HEADINGS + "\n## 모호한 관계명\n- old bullet\n"
        assert section_for(text, "모호") == "## 모호 (관계명·개념 판단 필요)"

    def test_the_scaffold_headings_are_what_section_for_returns(self):
        # Scaffolding and bullet placement read the same list: a bullet in a freshly
        # initialised KB lands under a heading that file actually has.
        for keyword, _ in REVIEW_CATEGORIES:
            assert section_for(OPEN_QUESTIONS_SCAFFOLD, keyword) in (
                OPEN_QUESTIONS_SCAFFOLD.splitlines()
            )
