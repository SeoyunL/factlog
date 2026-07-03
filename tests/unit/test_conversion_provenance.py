# SPDX-License-Identifier: Apache-2.0
"""Unit tests for ingest-conversion provenance helpers (#214, #229).

conversion_origin() must reduce both header formats — a legacy bare basename
and the #214 sources/-relative path — to the same basename, so every
basename-keyed consumer (paired_conversion, eject) is unaffected by the change.

conversion_body_is_empty() must flag a factlog conversion that has only its
provenance header (a scanned/image PDF -> silent 0-facts, #229) while never
flagging a plain source or a hand-placed file.
"""
from __future__ import annotations

import common


def _write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


class TestConversionOrigin:
    def test_legacy_basename_header(self, tmp_path):
        # Pre-#214 header recorded the bare basename.
        conv = _write(
            tmp_path / "data.hwpx.md",
            "<!-- ingested-by-factlog | source: data.hwpx | converter: x | date: y -->\n\nbody\n",
        )
        assert common.conversion_origin(conv) == "data.hwpx"

    def test_relative_path_header_reduces_to_basename(self, tmp_path):
        # #214: a sources/-relative header still yields the basename, so legacy
        # basename-comparing consumers keep working unchanged.
        conv = _write(
            tmp_path / "data.hwpx.md",
            "<!-- ingested-by-factlog | source: sub_a/data.hwpx | converter: x | date: y -->\n\nbody\n",
        )
        assert common.conversion_origin(conv) == "data.hwpx"

    def test_deeply_nested_relative_path(self, tmp_path):
        conv = _write(
            tmp_path / "x.pdf.txt",
            "[ingested-by-factlog] source: a/b/c/report.pdf | converter: x | date: y\n\nbody\n",
        )
        assert common.conversion_origin(conv) == "report.pdf"

    def test_no_header_returns_none(self, tmp_path):
        conv = _write(tmp_path / "hand.md", "just some text, no header\n")
        assert common.conversion_origin(conv) is None

    def test_empty_source_returns_none(self, tmp_path):
        conv = _write(
            tmp_path / "x.md",
            "<!-- ingested-by-factlog | source:  | converter: x | date: y -->\n\nbody\n",
        )
        assert common.conversion_origin(conv) is None


class TestConversionBodyIsEmpty:
    def test_header_only_is_empty(self, tmp_path):
        # A scanned PDF converts to header-only output (#229).
        conv = _write(
            tmp_path / "scan.pdf.txt",
            "[ingested-by-factlog] source: scan.pdf | converter: pdftotext | date: y\n\n",
        )
        assert common.conversion_body_is_empty(conv) is True

    def test_header_plus_whitespace_is_empty(self, tmp_path):
        conv = _write(
            tmp_path / "scan.pdf.txt",
            "[ingested-by-factlog] source: scan.pdf | converter: pdftotext | date: y\n\n  \n\n",
        )
        assert common.conversion_body_is_empty(conv) is True

    def test_header_with_text_is_not_empty(self, tmp_path):
        conv = _write(
            tmp_path / "doc.pdf.txt",
            "[ingested-by-factlog] source: doc.pdf | converter: pdftotext | date: y\n\nHello world\n",
        )
        assert common.conversion_body_is_empty(conv) is False

    def test_plain_source_without_header_is_not_flagged(self, tmp_path):
        # A blank *plain* source (no factlog header) is not an ingest conversion,
        # so this helper must not judge it as "converted-but-empty".
        conv = _write(tmp_path / "notes.md", "   \n")
        assert common.conversion_body_is_empty(conv) is False

    def test_missing_file_is_not_empty(self, tmp_path):
        assert common.conversion_body_is_empty(tmp_path / "nope.md") is False
