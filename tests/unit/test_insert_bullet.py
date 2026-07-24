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
