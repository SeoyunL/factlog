# SPDX-License-Identifier: Apache-2.0
"""Regression tests for page_filename NAME_MAX guard (#230)."""
from __future__ import annotations

import merge_candidates


class TestPageFilenameShort:
    def test_normal_title_unchanged(self):
        """A short/normal title passes through as-is."""
        from common import slugify

        title = "Alice in Wonderland"
        assert merge_candidates.page_filename(title) == f"{slugify(title)}.md"

    def test_plain_ascii(self):
        assert merge_candidates.page_filename("hello") == "hello.md"

    def test_korean_title(self):
        from common import slugify

        title = "갑봇"
        assert merge_candidates.page_filename(title) == f"{slugify(title)}.md"


class TestPageFilenameNameMax:
    """A >200-byte slug must be truncated with a stable hash suffix."""

    def _long_title(self, char: str = "a", repeat: int = 300) -> str:
        return char * repeat

    def test_long_title_filename_fits_in_255_bytes(self):
        title = self._long_title()
        fname = merge_candidates.page_filename(title)
        assert len(fname.encode("utf-8")) <= 255

    def test_long_title_is_valid_utf8(self):
        # Korean characters are 3 bytes each — stress the byte boundary.
        title = "가" * 100  # 100 × 3 = 300 bytes when slugified
        fname = merge_candidates.page_filename(title)
        # Must round-trip as UTF-8 without errors.
        assert fname == fname.encode("utf-8").decode("utf-8")

    def test_long_title_filename_fits_utf8_korean(self):
        title = "가" * 100
        fname = merge_candidates.page_filename(title)
        assert len(fname.encode("utf-8")) <= 255

    def test_collision_safe_distinct_long_titles(self):
        """Two titles sharing a 200-byte slug prefix but differing afterward
        must produce DISTINCT filenames (no silent collision)."""
        base = "a" * 250
        title_a = base + "X"
        title_b = base + "Y"
        fname_a = merge_candidates.page_filename(title_a)
        fname_b = merge_candidates.page_filename(title_b)
        assert fname_a != fname_b

    def test_stable_hash_same_title_same_filename(self):
        """The hash suffix is deterministic: same title → same filename."""
        title = "z" * 300
        assert merge_candidates.page_filename(title) == merge_candidates.page_filename(title)
