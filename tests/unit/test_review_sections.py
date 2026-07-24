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

from factlog.md_lines import (
    bullets,
    ends_inside_fence,
    headings,
    section_end_index,
    section_line_index,
    unclosed_fence_line,
)
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

    def test_an_unclosed_fence_does_not_get_a_duplicate_heading(self):
        """Regression (#504): this file grew three byte-identical headings per pass.

        An unclosed fence hides everything after it from the heading scan, so the
        categories below it read as missing and were appended again — a second copy
        of the exact same heading line, the queue left under the hidden first one,
        and split_review_sections unable to see that original to warn about it. The
        very split this module exists to prevent, manufactured by it.

        Inside this function the unclosed-fence check is the only thing that stops
        it, so removing that check fails this. It is a **library contract, not the
        pipeline's defence**: merge_candidates' writers call `refuse_unclosed_fence`
        first and never reach here with such a file, so deleting the check leaves
        every end-to-end test green. That is exactly why this case is a unit test.
        """
        doc = (
            "# Open Questions\n\n## 중복 개념 후보\n\n```\n"
            "## 모호한 관계명\n- 기존 큐가 여기 있다\n\n"
            "## 출처 부족\n\n## 기존 내용과 충돌할 수 있는 항목\n"
        )
        out = ensure_review_sections(doc)
        assert out == doc, "a hidden heading was copied instead of left alone"
        assert ensure_review_sections(out) == out
        for _, heading in REVIEW_CATEGORIES:
            assert out.splitlines().count(heading) <= 1, (heading, out)

    def test_nothing_is_written_into_an_unclosed_fence(self):
        """A file that never closes a fence is left alone and reported, not patched.

        Appending is appending to the end, and the end is inside the fence — every
        heading written there is invisible to the scan that asked for it. Measured:
        scaffolding this file produced three headings that still read as missing.
        """
        doc = "# Open Questions\n\n```\n## 모호한 관계명\n"
        out = ensure_review_sections(doc)
        assert out == doc
        assert missing_review_sections(out) == KEYWORDS  # loud, all four
        assert ensure_review_sections(out) == out

    @pytest.mark.parametrize("keyword,canonical", list(REVIEW_CATEGORIES))
    def test_a_category_whose_only_copy_is_fenced_gets_a_real_section(
        self, keyword, canonical
    ):
        """A fenced heading is an example, so the category is genuinely absent.

        Writing the real section is the repair, and it is safe now that every lookup
        skips fenced lines: section_line_index finds the one this adds, not the
        example. An earlier cut refused to write it — the copy in the fence looked
        like "already there" — and left the document permanently a section short with
        no way to earn it back.
        """
        others = "\n\n".join(h for k, h in REVIEW_CATEGORIES if k != keyword)
        doc = f"# Open Questions\n\n{others}\n\n예시:\n\n```\n{canonical}\n```\n"
        out = ensure_review_sections(doc)
        assert missing_review_sections(out) == []
        assert ensure_review_sections(out) == out
        # one real section, plus the example that is not one
        assert headings(out).count(canonical) == 1
        lines = out.splitlines()
        fenced_at = lines.index(canonical)  # the example, first in raw line order
        assert section_line_index(out, canonical) > fenced_at

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


class TestFenceScanning:
    """What counts as a fence, and what an unclosed one means.

    One scan answers all of it now. It was written out twice — once for headings,
    once for "does the file end mid-fence" — and two copies of the rule for what a
    section is are the disease #495 was about.
    """

    @pytest.mark.parametrize("marker", ["```", "~~~"])
    def test_either_fence_marker_can_leave_a_file_open(self, marker):
        # `~~~` had no test at all: deleting it from the scan changed nothing.
        doc = f"# Open Questions\n\n{marker}\n## 모호한 관계명\n"
        assert ends_inside_fence(doc) is True
        assert unclosed_fence_line(doc) == 3
        assert missing_review_sections(doc) == KEYWORDS

    @pytest.mark.parametrize("marker", ["```", "~~~"])
    def test_a_closed_fence_leaves_the_file_open_to_writing(self, marker):
        doc = f"# Open Questions\n\n{marker}\n## 모호한 관계명\n{marker}\n"
        assert ends_inside_fence(doc) is False
        assert unclosed_fence_line(doc) is None

    def test_three_spaces_of_indent_is_still_a_fence(self):
        # CommonMark: up to three spaces of indent, and it is a fence.
        doc = "# Open Questions\n\n   ```\n## 모호한 관계명\n"
        assert ends_inside_fence(doc) is True

    def test_four_spaces_of_indent_is_an_indented_code_block_not_a_fence(self):
        """A well-formed document was being read as permanently unclosed.

        At four spaces the line is an indented code block — content that opens
        nothing — so the headings below it are real and the file validates.
        """
        doc = (
            "# Open Questions\n\n## 중복 개념 후보\n\n예시:\n\n    ```\n\n"
            "## 모호한 관계명\n\n## 출처 부족\n\n## 기존 내용과 충돌할 수 있는 항목\n"
        )
        assert ends_inside_fence(doc) is False
        assert missing_review_sections(doc) == []

    def test_an_odd_number_of_fences_really_does_end_open(self):
        # Not a false positive: the third fence opens and nothing closes it.
        doc = "# Open Questions\n\n```\na\n```\n\n## 모호한 관계명\n\n```\nb\n"
        assert ends_inside_fence(doc) is True
        assert unclosed_fence_line(doc) == 9

    def test_a_tilde_block_may_quote_a_backtick_line(self):
        """The document this module's own reference tells people to write.

        Anyone spelling out the bullet format wraps the example in ``~~~`` precisely
        so the backticks inside need no escaping. Toggling on any marker made the
        quoted ``` "close" the tilde fence and the real ``~~~`` re-open it, so a
        correct file read as permanently unclosed: both writers refused it forever,
        pointing at the line that closes it and asking for it to be closed.
        """
        doc = (
            "# Open Questions\n\n## 중복 개념 후보\n\n## 모호한 관계명\n\n형식 예시:\n\n"
            "~~~\n- needs_review: X / r / Y\n```\n~~~\n\n"
            "## 출처 부족\n\n## 기존 내용과 충돌할 수 있는 항목\n"
        )
        assert ends_inside_fence(doc) is False
        assert unclosed_fence_line(doc) is None
        assert missing_review_sections(doc) == []
        assert bullets(doc) == []  # the example is still not a filed bullet

    def test_a_backtick_block_may_quote_a_tilde_line(self):
        doc = "# Open Questions\n\n```\n~~~\n```\n\n## 모호한 관계명\n"
        assert ends_inside_fence(doc) is False
        assert headings(doc) == ["## 모호한 관계명"]

    def test_a_longer_run_closes_but_a_shorter_one_does_not(self):
        # CommonMark: the closing run is at least as long as the opening one.
        assert ends_inside_fence("# Open Questions\n\n```\nx\n`````\n") is False
        assert ends_inside_fence("# Open Questions\n\n`````\nx\n```\n") is True

    def test_a_marker_carrying_an_info_string_cannot_close(self):
        # ```python opens a block; it never ends one.
        assert ends_inside_fence("# Open Questions\n\n```\nx\n```python\n") is True


class TestReviewBullets:
    """What counts as a filed bullet — the reader both the producer and validator use.

    They each had their own before, and both counted lines inside code fences. A KB
    that documents its own bullet format in a fence therefore had the example stand in
    for the queue: the producer skipped the first real bullet as a duplicate of it,
    and the validator accepted it as proof that review bullets existed.
    """

    def test_a_bullet_in_a_fence_is_not_a_filed_bullet(self):
        text = "# Open Questions\n\n형식 예시:\n\n```\n- needs_review: X / r / Y\n```\n"
        assert bullets(text) == []

    def test_real_bullets_are_returned_raw(self):
        text = "# Open Questions\n\n## 출처 부족\n- needs_review: X / r / Y\n  - nested\n"
        assert bullets(text) == ["- needs_review: X / r / Y", "  - nested"]

    def test_the_example_and_the_real_bullet_are_told_apart(self):
        bullet = "- needs_review: W / related_to / G"
        text = f"# Open Questions\n\n```\n{bullet}\n```\n\n## 모호한 관계명\n{bullet}\n"
        assert bullets(text) == [bullet]

    def test_a_dash_that_is_not_a_list_item_does_not_count(self):
        assert bullets("# Open Questions\n\n---\n-notabullet\n") == []


class TestSectionLookup:
    """Where a section starts and ends — the answer insert_bullet now shares.

    It used to keep its own: `lines.index(heading)` and a `startswith("## ")` scan,
    neither of which knew about fences. Measured on that code, a bullet was filed
    against a heading inside a code fence and written just past the closing fence,
    under no section at all, and the run exited 0.
    """

    FENCED = (
        "# Open Questions\n\n"          # 0,1
        "## 중복 개념 후보\n\n"           # 2,3
        "```\n"                          # 4
        "## 출처 부족\n"                  # 5  <- example, not a section
        "```\n\n"                        # 6,7
        "## 출처 부족\n"                  # 8  <- the real one
        "- 기존 항목\n"                   # 9
    )

    def test_a_fenced_heading_is_never_the_section(self):
        assert section_line_index(self.FENCED, "## 출처 부족") == 8

    def test_a_missing_section_is_none_rather_than_a_guess(self):
        assert section_line_index(self.FENCED, "## 모호한 관계명") is None

    def test_a_section_runs_to_the_next_real_heading(self):
        #    0                 1   2               3     4   5            6
        doc = "# Open Questions\n\n## 중복 개념 후보\n- a\n\n## 출처 부족\n- b\n"
        assert section_end_index(doc, 2) == 5

    def test_a_section_with_no_heading_after_it_runs_to_the_end(self):
        doc = "# Open Questions\n\n## 중복 개념 후보\n- a\n"
        assert section_end_index(doc, 2) == 4

    def test_a_fenced_heading_does_not_cut_a_section_short(self):
        """The end scan skips fenced `## ` lines too, or a bullet lands in the fence."""
        #    0                 1   2               3     4     5            6     7     8   9
        doc = (
            "# Open Questions\n\n## 중복 개념 후보\n- a\n"
            "```\n## 출처 부족\n```\n"
            "- b\n\n## 출처 부족\n"
        )
        assert section_end_index(doc, 2) == 9


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
