# SPDX-License-Identifier: Apache-2.0
"""The import/refresh/search commands' remaining `--porcelain` rows keep their shape (#416).

`porcelain.py` names the positional contract — a fixed field count read by column offset.
#406 closed the three search `result` rows and said in its own docstring that it was not
closing the set. This file closes what that note listed, plus one emitter the note did not
have: the `candidate` row.

Scope, stated exactly, because #406's first draft of this sentence overreached: what is
covered below is **twelve** emitters — two `query` rows, four dry-run `item`/`work` rows,
five `target` rows and the `candidate` row — carrying **seventeen** caller-influenced
columns between them. #416 gated eleven of the twelve (fifteen of the seventeen columns);
the twelfth, `_pubmed_finish`'s `work` row, was gated by #141 and is covered here as a
regression guard and as the control that this shape *can* be checked.

Add the four groups up rather than trusting the total: an earlier draft of this paragraph
said "eleven emitters" over a list that adds to twelve, which is a small instance of this
file's own subject. This is *not* a survey — `porcelain.py` remains the one place that
records what is and is not gated.

**Reachability is not uniform across the twelve, and the tests do not pretend it is.**
Measured end to end, a tab reaching the row and adding a column:

* both `query` rows (`--query $'a\\tb' --show-query --porcelain`),
* all five `target` rows (a KB in a directory whose name holds a tab),
* the zotero `item` row (a Zotero key holding a tab),
* the arXiv `work` row (a versioned id holding a tab, from the client response),
* the pubmed `work` row (a PMID holding a tab, from an efetch body — it arrives and is
  neutralized to a space, which is what #141's gate looks like from outside),
* the `candidate` row (an OpenAlex id holding a tab, through the real importer).

The OpenAlex `work` row is the exception: `openalex-import` rejects a response id that is
not `W<digits>`, and a hostile title is slugified before it reaches the filename column, so
no route was found that carries a tab there — measured, not assumed. It is gated anyway and
tested at the emitter, on the argument #406 already settled: `outcome.key` *is*
`work.openalex_id`, the same value `_openalex_show_results` gates one row over. A caller
gates its value rather than reasoning about what its own parser admits; reasoning the other
way is the error #396's first cut shipped.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from factlog import cli
from factlog.integrations.common.porcelain import _LINE_BREAKS

# Exactly the set the gate covers — tab plus every `_LINE_BREAKS` character — plus U+0020
# SPACE, which it does not. The space is a negative control: it must stay green with the
# gate reverted, which is what shows the rest of this file goes red for the gate and not
# because the assertions reject everything.
#
# Verify by code point, never by eye: `[f"U+{ord(c):04X}" for c in HOSTILE]` is 12 long and
# contains U+0020. #406 shipped a revision of this line with U+2028 where the space belongs
# — it renders as a space in a terminal — so the control it documented did not exist, and
# nothing ever collected a U+0020 case to notice. The ids below are code points for the
# same reason: a `-k "U+0020"` selection must be able to find the control and count it.
HOSTILE = sorted({"\t", " ", *_LINE_BREAKS})
CHAR_IDS = [f"U+{ord(c):04X}" for c in HOSTILE]


def _assert_row(capsys, token, *, columns, lines):
    """Assert the ``token`` row has ``columns`` fields and the output has ``lines`` lines.

    Both dimensions, always, because they fail independently and neither implies the
    other — and because checking only one is a live way to write a test that passes for
    the wrong reason. Measured, on this file: with only the column count asserted, eleven
    of the seventeen mutants below were killed by the tab case alone. A line break in the
    *last* column splits the row into a head that still has the full field count and an
    orphan tail on its own line, so the column count reads clean while a consumer is
    handed a row that is not there. The line count is what sees the orphan; it is taken
    over every line printed, never over the ``token``-prefixed ones, since a prefix filter
    counts the head and passes for exactly the same reason.

    Returns the row so a caller can assert on its content.
    """
    out = capsys.readouterr().out.splitlines()
    rows = [ln for ln in out if ln.split("\t", 1)[0] == token]
    assert len(rows) == 1, f"expected one {token} row, got {rows!r} in {out!r}"
    assert len(rows[0].split("\t")) == columns, f"field count drifted: {rows[0]!r}"
    assert len(out) == lines, f"a row split — expected {lines} lines, got {out!r}"
    return rows[0]


def _outcome(status="imported", key="W1", name="a-paper.md"):
    path = SimpleNamespace(name=name) if name is not None else None
    # `title` and `withdrawn_by` feed the stderr warning helpers the finish functions run
    # alongside the porcelain rows; a clean value there keeps stderr out of the way.
    return SimpleNamespace(status=status, key=key, path=path, title="A paper",
                           withdrawn_by=None)


def _report(outcomes=(), candidates=()):
    return SimpleNamespace(
        outcomes=list(outcomes), candidates=list(candidates),
        imported=len(outcomes), skipped=0, merged=0, errors=0,
        candidate_ledger_error=None,
    )


def _kb(tmp_path):
    (tmp_path / "sources").mkdir(exist_ok=True)
    return tmp_path


def _finish(fn, report, target):
    """Call one of the three `_*_finish` helpers; they differ only in their warning kwarg."""
    kw = {"warning": ""} if fn is cli._openalex_finish else {"warnings": []}
    return fn(report, target, dry_run=True, porcelain=True, **kw)


# --------------------------------------------------------------------------- #
# The `query` row — the most caller-influenced value on any porcelain row.
# --------------------------------------------------------------------------- #
QUERY_COMMANDS = [
    ("arxiv-search", ["arxiv-search"]),
    ("pubmed-search", ["pubmed-search"]),
]
QUERY_IDS = [name for name, _ in QUERY_COMMANDS]


@pytest.mark.parametrize("char", HOSTILE, ids=CHAR_IDS)
@pytest.mark.parametrize("name, argv", QUERY_COMMANDS, ids=QUERY_IDS)
class TestTheQueryRow:
    def test_the_row_stays_one_line_of_two_columns(self, name, argv, char, tmp_path,
                                                   capsys):
        # End to end through the real command: `--show-query` spends no request and
        # returns before any client is built, so this is the whole path a user takes.
        args = cli.build_parser().parse_args(
            [*argv, "--query", f"a{char}b", "--show-query", "--porcelain",
             "--target", str(_kb(tmp_path))])
        assert args.func(args) == 0
        # `--show-query` prints the row and nothing else, so the whole output is one line.
        _assert_row(capsys, "query", columns=2, lines=1)


# --------------------------------------------------------------------------- #
# The dry-run `item`/`work` row — one shape, four emitters, one of them gated before #416.
# --------------------------------------------------------------------------- #
DRY_RUN_ROWS = [
    ("openalex-import", "work", cli._openalex_finish),
    ("arxiv-import", "work", cli._arxiv_finish),
    ("pubmed-import", "work", cli._pubmed_finish),
]
DRY_RUN_IDS = [name for name, _, _ in DRY_RUN_ROWS]

# The two caller-influenced columns of that row, varied one at a time so a mutant that
# reverts one gate is distinguishable from a mutant that reverts the other. Tested
# together they are not: either revert fails "the key column" and "the name column" alike.
COLUMNS = ["key", "name"]


@pytest.mark.parametrize("column", COLUMNS)
@pytest.mark.parametrize("char", HOSTILE, ids=CHAR_IDS)
@pytest.mark.parametrize("name, token, fn", DRY_RUN_ROWS, ids=DRY_RUN_IDS)
class TestTheDryRunWorkRow:
    def test_the_row_stays_one_line_of_four_columns(self, name, token, fn, char, column,
                                                    tmp_path, capsys):
        hostile = f"a{char}b"
        outcome = _outcome(key=hostile if column == "key" else "W1",
                           name=hostile if column == "name" else "a-paper.md")
        _finish(fn, _report([outcome]), tmp_path)
        # The work row + imported/skipped/merged/errors/dry_run/target + candidates.
        _assert_row(capsys, token, columns=4, lines=8)

    def test_two_works_are_two_rows_and_two_lines(self, name, token, fn, char, column,
                                                  tmp_path, capsys):
        # The count is what a consumer reads to know it has every work. Two outcomes must
        # be two `work` lines, never three because one key carried a break.
        hostile = f"a{char}b"
        outcomes = [
            _outcome(key=hostile if column == "key" else f"W{i}",
                     name=hostile if column == "name" else f"p{i}.md")
            for i in (1, 2)
        ]
        _finish(fn, _report(outcomes), tmp_path)
        lines = capsys.readouterr().out.splitlines()
        assert sum(ln.startswith(f"{token}\t") for ln in lines) == 2
        assert len(lines) == 9, f"a row split: {lines!r}"


@pytest.mark.parametrize("column", COLUMNS)
@pytest.mark.parametrize("char", HOSTILE, ids=CHAR_IDS)
class TestTheZoteroItemRow:
    """`zotero-import`'s dry-run row, the fourth sibling — emitted inline, not via a helper."""

    def test_the_row_stays_one_line_of_four_columns(self, char, column, tmp_path,
                                                    monkeypatch, capsys):
        from factlog.integrations.zotero import importer as zotero_importer

        hostile = f"a{char}b"
        outcome = _outcome(key=hostile if column == "key" else "K1",
                           name=hostile if column == "name" else "a-paper.md")
        report = SimpleNamespace(
            outcomes=[outcome], imported=1, skipped=0, errors=0, pdf_outcomes=[],
            pdf_placed=0, pdf_skipped=0, pdf_errors=0, annotations_written=0,
            annotations_updated=0, annotations_skipped=0, annotation_errors=0,
        )
        monkeypatch.setattr(zotero_importer, "import_items", lambda *a, **k: report)
        monkeypatch.setattr(cli, "_make_zotero_client", lambda config: object())
        (tmp_path / "sources").mkdir()
        assert cli.main(["zotero-import", "--tag", "t", "--target", str(tmp_path),
                         "--porcelain", "--dry-run"]) == 0
        # The item row + imported/skipped/errors/dry_run/target.
        _assert_row(capsys, "item", columns=4, lines=6)


# --------------------------------------------------------------------------- #
# The `target` row — a path built from the user's `--target`, five emitters.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("char", HOSTILE, ids=CHAR_IDS)
@pytest.mark.parametrize("name, fn", [(n, f) for n, _, f in DRY_RUN_ROWS], ids=DRY_RUN_IDS)
class TestTheTargetRowFromAFinishHelper:
    def test_the_row_stays_one_line_of_two_columns(self, name, fn, char, tmp_path, capsys):
        # A POSIX filename may hold a tab, or a newline, outright — `mkdir` accepts both,
        # so the directory below is a real one and the path is a real path.
        target = tmp_path / f"kb{char}x"
        target.mkdir()
        _finish(fn, _report(), target)
        # imported/skipped/merged/errors/dry_run/target/candidates.
        row = _assert_row(capsys, "target", columns=2, lines=7)
        assert row.endswith("/sources"), f"the path lost its tail: {row!r}"


@pytest.mark.parametrize("char", HOSTILE, ids=CHAR_IDS)
class TestTheTargetRowFromZoteroImport:
    def test_the_row_stays_one_line_of_two_columns(self, char, tmp_path, monkeypatch,
                                                   capsys):
        from factlog.integrations.zotero import importer as zotero_importer

        target = tmp_path / f"kb{char}x"
        (target / "sources").mkdir(parents=True)
        report = SimpleNamespace(
            outcomes=[], imported=0, skipped=0, errors=0, pdf_outcomes=[],
            pdf_placed=0, pdf_skipped=0, pdf_errors=0, annotations_written=0,
            annotations_updated=0, annotations_skipped=0, annotation_errors=0,
        )
        monkeypatch.setattr(zotero_importer, "import_items", lambda *a, **k: report)
        monkeypatch.setattr(cli, "_make_zotero_client", lambda config: object())
        assert cli.main(["zotero-import", "--tag", "t", "--target", str(target),
                         "--porcelain"]) == 0
        # imported/skipped/errors/dry_run/target.
        _assert_row(capsys, "target", columns=2, lines=5)


@pytest.mark.parametrize("char", HOSTILE, ids=CHAR_IDS)
class TestTheTargetRowFromPubmedRefresh:
    """The fifth `target` row — `pubmed-refresh --dry-run`, which prints the KB, not `sources/`.

    Two rows above it in the same block already went through the gate before #416; this one
    did not. A gap that narrow is the argument for one shared definition over a per-call
    judgement, and it is the emitter #416 measured first.
    """

    def test_the_row_stays_one_line_of_two_columns(self, char, tmp_path, monkeypatch,
                                                   capsys):
        target = tmp_path / f"kb{char}x"
        (target / "sources").mkdir(parents=True)
        (target / "policy").mkdir()
        (target / "policy" / "pubmed-config.toml").write_text(
            '[client]\nemail = "test@example.com"\n', encoding="utf-8")
        (target / "sources" / "a.md").write_text(
            "---\npmid: 111\nimported_from: pubmed\njournal: J\n---\n\n# Paper\n",
            encoding="utf-8")
        # A dry run spends no request; the client must never be asked.
        monkeypatch.setattr(cli, "_make_pubmed_client", lambda config: object())
        args = cli.build_parser().parse_args(
            ["pubmed-refresh", "--target", str(target), "--dry-run", "--porcelain"])
        assert args.func(args) == 0
        # would-check (one paper) + would_check/skipped/dry_run/target.
        _assert_row(capsys, "target", columns=2, lines=5)


# --------------------------------------------------------------------------- #
# The `candidate` row (#75) — the emitter `porcelain.py`'s #406 note did not list.
# --------------------------------------------------------------------------- #
CANDIDATE_COLUMNS = ["key", "existing_path"]


@pytest.mark.parametrize("column", CANDIDATE_COLUMNS)
@pytest.mark.parametrize("char", HOSTILE, ids=CHAR_IDS)
class TestTheCandidateRow:
    def test_the_row_stays_one_line_of_four_columns(self, char, column, tmp_path, capsys):
        hostile = f"a{char}b"
        candidate = SimpleNamespace(
            existing_path=SimpleNamespace(
                name=hostile if column == "existing_path" else "existing.md"),
            score=1.0,
        )
        surfaced = SimpleNamespace(key=hostile if column == "key" else "W1",
                                   candidate=candidate)
        _finish(cli._openalex_finish, _report(candidates=[surfaced]), tmp_path)
        # imported/skipped/merged/errors/dry_run/target + candidate + candidates.
        _assert_row(capsys, "candidate", columns=4, lines=8)


# --------------------------------------------------------------------------- #
# Ordinary output is byte-unchanged.
# --------------------------------------------------------------------------- #
class TestOrdinaryOutputIsUnchanged:
    """The gate replaces tabs and line breaks and nothing else.

    A row with neither must read exactly as it did before #416, so a consumer parsing the
    six summary tokens sees no drift. This is the half of the contract the hostile cases
    cannot check: a gate that replaced every character would satisfy every assertion above.
    """

    def test_a_clean_work_row_survives_verbatim(self, tmp_path, capsys):
        _finish(cli._arxiv_finish, _report([_outcome(key="2401.00001v1")]), tmp_path)
        lines = capsys.readouterr().out.splitlines()
        assert lines[0] == "work\timported\t2401.00001v1\ta-paper.md"

    def test_a_clean_target_row_survives_verbatim(self, tmp_path, capsys):
        _finish(cli._arxiv_finish, _report(), tmp_path)
        rows = dict(ln.split("\t", 1) for ln in capsys.readouterr().out.splitlines())
        assert rows["target"] == str(tmp_path / "sources")

    def test_a_clean_query_row_survives_verbatim(self, tmp_path, capsys):
        args = cli.build_parser().parse_args(
            ["pubmed-search", "--query", "crispr gene editing", "--show-query",
             "--porcelain", "--target", str(_kb(tmp_path))])
        args.func(args)
        assert _assert_row(capsys, "query", columns=2, lines=1) == \
            "query\tcrispr gene editing"

    def test_a_missing_path_stays_an_empty_last_field(self, tmp_path, capsys):
        _finish(cli._arxiv_finish, _report([_outcome(key="W1", name=None)]), tmp_path)
        assert capsys.readouterr().out.splitlines()[0] == "work\timported\tW1\t"
