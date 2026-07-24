# SPDX-License-Identifier: Apache-2.0
"""Regression tests for merge_candidates.insert_bullet idempotency (#104)."""
from __future__ import annotations

import merge_candidates as mc
from factlog.review_sections import ensure_review_sections, section_for

SECTION = "## 출처 부족"


def _at(text: str):
    """Where the 출처 section is — the same answer the producer gets."""
    return section_for(text, "출처")


class TestInsertBullet:
    def test_exact_duplicate_is_skipped(self):
        base = f"# Open Questions\n\n{SECTION}\n- foo\n"
        assert mc.insert_bullet(base, _at(base), "- foo") == base

    def test_prefix_substring_bullet_is_still_added(self):
        # #104: "- note" must NOT be considered present just because
        # "- note extra" already is.
        base = f"# Open Questions\n\n{SECTION}\n- note extra\n"
        out = mc.insert_bullet(base, _at(base), "- note")
        assert "- note extra" in out
        # the new shorter bullet was actually inserted as its own line
        assert any(line.rstrip() == "- note" for line in out.splitlines())

    def test_the_section_is_scaffolded_before_the_bullet_is_filed(self):
        """A file with no 출처 section gets one from `ensure_review_sections`.

        `insert_bullet` used to append a heading of its own when the section was not
        found. That fallback wrote into a document whose shape nobody had checked —
        into an unclosed fence, measured — so it is gone: the writers scaffold first
        and `section_for` is loud if they did not.
        """
        text = ensure_review_sections("# Open Questions\n")
        out = mc.insert_bullet(text, _at(text), "- bar")
        assert SECTION in out and "- bar" in out


class TestInsertBulletIntoASetextSection:
    """A Setext heading is two lines, and the blank-line guards have to know it.

    `heading.start + 1` is the underline, not the end of the heading, so a guard
    written against it sees a non-blank line where the heading itself is and inserts
    a blank line that does not belong to the file.
    """

    ADJACENT = "출처\n----\n충돌\n----\n"

    def test_an_empty_section_gets_the_bullet_flush_under_its_underline(self):
        out = mc.insert_bullet(self.ADJACENT, _at(self.ADJACENT), "- b")
        assert out.splitlines() == ["출처", "----", "- b", "", "충돌", "----"]

    def test_a_section_with_content_keeps_one_blank_line_before_the_bullet(self):
        text = "출처\n----\n문단\n\n충돌\n----\n"
        out = mc.insert_bullet(text, _at(text), "- b")
        assert out.splitlines() == [
            "출처", "----", "문단", "", "- b", "", "충돌", "----",
        ]
