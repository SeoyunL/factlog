# SPDX-License-Identifier: Apache-2.0
"""Regression tests for validate's heading-anchor slug logic (#105)."""
from __future__ import annotations

import validate


class TestSlugifyHeading:
    def test_plain(self):
        assert validate.slugify_heading("My Heading") == "my-heading"

    def test_strips_punctuation(self):
        # The bug: "## Plan (v2)" must anchor as "plan-v2", not "plan-(v2)".
        assert validate.slugify_heading("Plan (v2)") == "plan-v2"

    def test_keeps_unicode_letters(self):
        assert validate.slugify_heading("한글 제목") == "한글-제목"

    def test_keeps_existing_hyphen(self):
        assert validate.slugify_heading("Pre-flight Check") == "pre-flight-check"


class TestHeadingSlugs:
    def test_styled_heading_anchor_resolves(self):
        slugs = validate.heading_slugs("# Plan (v2)\n\nbody\n")
        assert "plan-v2" in slugs

    def test_duplicate_headings_suffixed(self):
        slugs = validate.heading_slugs("# Notes\n## Notes\n")
        assert "notes" in slugs
        assert "notes-1" in slugs

    def test_legacy_naive_slug_still_accepted(self):
        # Backward compat: a ref authored against the old slug still validates.
        slugs = validate.heading_slugs("# Plan (v2)\n")
        assert "plan-(v2)" in slugs


class TestValidateSourceRef:
    def test_styled_section_no_longer_false_errors(self, tmp_path):
        (tmp_path / "doc.md").write_text("# Plan (v2)\n\nbody\n", encoding="utf-8")
        assert validate.validate_source_ref(tmp_path, "doc.md#plan-v2") is None

    def test_missing_section_still_reported(self, tmp_path):
        (tmp_path / "doc.md").write_text("# Intro\n", encoding="utf-8")
        err = validate.validate_source_ref(tmp_path, "doc.md#nope")
        assert err and "section does not exist" in err
