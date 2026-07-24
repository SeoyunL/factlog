# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the folded 'skip row' diagnostic in normalize_rows (#492).

A missing source used to warn once per row, so a few stale paths pushed the
merge summary -- and the validate failures after it -- off the screen.  The
warning is now one line per anchor-stripped source path with a row count, in
path order, and it must still appear on the --strict early exit.

The --strict line is the one exception to the row count: strict exits on the
first offending row, so its count is a structural constant 1 rather than a
measurement, and the suffix is omitted there (#494).
"""
from __future__ import annotations

import re
import unicodedata

import pytest

import merge_candidates as mc


def _root_with_source(tmp_path, name="a.md"):
    """A KB root whose sources/ holds one real file, so rows referencing it
    pass the source-existence check inside normalize_rows."""
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / name).write_text("# heading\n", encoding="utf-8")
    return tmp_path


def _row(subject, relation, obj, source, status="candidate", confidence="0.50", note=""):
    return {
        "subject": subject,
        "relation": relation,
        "object": obj,
        "source": source,
        "status": status,
        "confidence": confidence,
        "note": note,
    }


def _missing_rows():
    """3 rows on one missing source (two of them differing only by anchor, so
    the fold must key on the anchor-stripped path) + 1 row on another."""
    return [
        _row("A", "rel", "B", "sources/gone.md"),
        _row("C", "rel", "D", "sources/gone.md#sec1"),
        _row("E", "rel", "F", "sources/gone.md#sec2"),
        _row("G", "rel", "H", "sources/other.md"),
    ]


def _skip_lines(capsys):
    err = capsys.readouterr().err
    return [line for line in err.splitlines() if line.strip().startswith("skip row:")]


class TestSkipRowSummary:
    def test_one_line_per_source_with_row_counts(self, tmp_path, capsys):
        root = _root_with_source(tmp_path)
        mc.normalize_rows(root, _missing_rows())
        lines = _skip_lines(capsys)
        assert len(lines) == 2
        assert "sources/gone.md" in lines[0] and "(3 rows)" in lines[0]
        assert "sources/other.md" in lines[1] and "(1 row)" in lines[1]

    def test_singular_and_plural_counts_in_one_run(self, tmp_path, capsys):
        """One line must read '(1 row)' and the other '(2 rows)' in the SAME run,
        so neither number can be hard-coded and 'row(s)' cannot stand in.

        The expected tail includes the closing paren of the hint clause and the
        ONE space before the suffix: that separator lives with the suffix so
        strict can omit it without leaving trailing whitespace (#494), which
        means a lost or doubled space here is exactly how this line would
        silently drift from the byte-identical output #492 fixed."""
        root = _root_with_source(tmp_path)
        rows = [
            _row("A", "rel", "B", "sources/one.md"),
            _row("C", "rel", "D", "sources/two.md"),
            _row("E", "rel", "F", "sources/two.md#sec1"),
        ]
        mc.normalize_rows(root, rows)
        lines = _skip_lines(capsys)
        assert len(lines) == 2
        assert "sources/one.md" in lines[0] and lines[0].endswith("') (1 row)")
        assert "sources/two.md" in lines[1] and lines[1].endswith("') (2 rows)")

    def test_count_folds_across_nfc_and_nfd_spellings(self, tmp_path, capsys):
        """The aggregation key is the NFC-normalised path (#57/#482): macOS
        stores filenames as NFD while extracted rows are typically NFC, so the
        two spellings of ONE missing path must fold into one line.  Keying on
        the raw row value would emit two lines that are indistinguishable on
        screen -- the exact scroll-flood #492 removes.  Both encodings are
        written explicitly here, so this is deterministic on any platform."""
        root = _root_with_source(tmp_path)
        nfc = "sources/각문서.md"
        nfd = unicodedata.normalize("NFD", nfc)
        assert nfc != nfd, "expected the NFC and NFD spellings to differ as strings"
        rows = [
            _row("A", "rel", "B", nfd),
            _row("C", "rel", "D", nfc),
        ]
        mc.normalize_rows(root, rows)
        lines = _skip_lines(capsys)
        assert len(lines) == 1
        assert "(2 rows)" in lines[0]
        # The reported path is the NFC form, matching what dedup/candidates.csv use.
        assert f"'{nfc}'" in lines[0]

    def test_line_order_is_independent_of_input_order(self, tmp_path, capsys):
        root = _root_with_source(tmp_path)
        forward = _missing_rows()
        mc.normalize_rows(root, forward)
        lines_forward = _skip_lines(capsys)
        mc.normalize_rows(root, list(reversed(forward)))
        lines_reverse = _skip_lines(capsys)
        assert lines_forward == lines_reverse

    def test_dropped_summary_and_returned_rows_unchanged(self, tmp_path, capsys):
        root = _root_with_source(tmp_path)
        rows = _missing_rows() + [_row("K", "rel", "L", "sources/a.md")]
        out = mc.normalize_rows(root, rows)
        err_lines = capsys.readouterr().err.splitlines()
        summary = "  warning: 4 row(s) dropped during normalise/dedup"
        assert summary in err_lines
        # Detail before summary: the whole point of #492 is that the summary --
        # and the validate failures printed after it -- stay on screen, which
        # only holds if the skip block is flushed BEFORE the summary line.
        last_skip = max(
            i for i, line in enumerate(err_lines) if line.strip().startswith("skip row:")
        )
        assert last_skip < err_lines.index(summary)
        # Only the row whose source exists survives.
        assert len(out) == 1
        assert out[0]["source"] == "sources/a.md"

    def test_strict_prints_the_summary_before_exiting(self, tmp_path, capsys):
        root = _root_with_source(tmp_path)
        with pytest.raises(SystemExit) as excinfo:
            mc.normalize_rows(root, _missing_rows(), strict=True)
        # strict still dies on the FIRST offending row, message unchanged.
        assert "--strict: input row rejected (source not found): sources/gone.md" in str(
            excinfo.value
        )
        lines = _skip_lines(capsys)
        assert len(lines) == 1
        assert "sources/gone.md" in lines[0]

    def test_strict_line_omits_the_row_count(self, tmp_path, capsys):
        """sources/gone.md carries 3 rows here, but strict exits on the first
        one, so any count it could print is a structural 1 -- a false quantity
        about how much that path is leaking (#494).  The suffix is dropped
        rather than corrected: strict has not seen the other rows.  Negate the
        suffix SHAPE, not the literal '(1 row)', so a variant that prints
        '(3 rows)' is caught too."""
        root = _root_with_source(tmp_path)
        with pytest.raises(SystemExit):
            mc.normalize_rows(root, _missing_rows(), strict=True)
        lines = _skip_lines(capsys)
        assert len(lines) == 1
        assert re.search(r"\(\d+ rows?\)", lines[0]) is None
        # Dropping the suffix must not leave the space that preceded it.
        assert lines[0].rstrip() == lines[0]
        # Dropping the suffix must not take the path or the diagnosis with it.
        # Narrowly these two only: the hint clause that follows them is not
        # pinned by any test (a pre-existing #492 gap, out of scope here).
        assert "sources/gone.md" in lines[0]
        assert "not found in sources/" in lines[0]
