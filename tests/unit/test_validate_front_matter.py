# SPDX-License-Identifier: Apache-2.0
"""validate.py warns when a source's front matter a human damaged (#422, #445).

The reader is fail-closed: a block it cannot delimit yields nothing at all, because
trusting such a block let a user's own note register its body lines as a paper's
identity, and that fails silently (#409). The trade is right, but its cost runs the
other way and had no signal — a tool-written source whose fence a human deleted stops
looking imported, drops out of de-duplication, and announces itself only when a second
``.md`` lands beside the first.

Two damage shapes carry that cost. #422 covers the *closing* fence: the block opens
and never closes. #445 covers the *opening* fence: the ``---`` is gone but the file
still opens with an importer identity key, the shape the writers' output takes once
that line is removed. The second is the hard one, because a bare missing opening fence
is also the normal shape of an ingest conversion and a hand-written note — so the
signal is the identity key, not the absence.

These pin both signals: which files are reported, which are not, that each tag names
only what the reader knows, and that saying so never turns a valid KB into a failing
one.
"""
from __future__ import annotations

import validate
from common import source_files

from factlog.front_matter_scan import (
    FRONT_MATTER_MAX_CHARS,
    FRONT_MATTER_NO_OPENING_FENCE,
    FRONT_MATTER_UNCLOSED,
    FRONT_MATTER_UNSCANNED,
)
from factlog.integrations.common.source_writer import IDENTITY_KEYS_BY_SOURCE

# A source as one of the writers renders it, trimmed to the keys that matter here.
INTACT = '---\nopenalex_id: "W2741809807"\ntitle: "A paper"\n---\n\nAbstract.\n'
# The same file after a human deleted the closing fence — the #422 case.
DAMAGED = '---\nopenalex_id: "W2741809807"\ntitle: "A paper"\n\nAbstract.\n'
# The same file after a human deleted the *opening* fence — the #445 case. The
# closing ``---`` and every key survive; only the first ``---`` is gone, so the file
# now opens with the writer's identity key at column 0.
OPENING_DELETED = 'openalex_id: "W2741809807"\ntitle: "A paper"\n---\n\nAbstract.\n'


def _sources(root, **files) -> None:
    """Write ``sources/<name>`` for each keyword, creating the directory."""
    (root / "sources").mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (root / "sources" / name.replace("__", ".")).write_text(text, encoding="utf-8")


class TestWhichFilesAreReported:
    def test_a_damaged_source_is_reported(self, tmp_path):
        _sources(tmp_path, damaged__md=DAMAGED)
        warnings = validate.front_matter_warnings(tmp_path)
        assert len(warnings) == 1
        tag, message = warnings[0]
        assert tag == "no_closing_fence"
        assert message.startswith("sources/damaged.md: ")
        assert FRONT_MATTER_UNCLOSED in message

    def test_an_intact_source_is_not_reported(self, tmp_path):
        """The control that keeps the test above from passing on any source at all.

        Both files carry the same keys and differ only by the closing fence, so a
        check that reported on the wrong property would fail here.
        """
        _sources(tmp_path, intact__md=INTACT, damaged__md=DAMAGED)
        warnings = validate.front_matter_warnings(tmp_path)
        assert [message.split(":")[0] for _tag, message in warnings] == ["sources/damaged.md"]

    def test_a_conversion_without_front_matter_is_not_reported(self, tmp_path):
        """An ingest conversion carries an HTML comment, not YAML.

        It has no opening fence, so the reader returns nothing for it too. These
        are the ordinary majority of a source tree, and warning on them would bury
        the one file that is actually damaged.
        """
        _sources(tmp_path, converted__md="<!-- provenance: report.pdf -->\n\nText.\n")
        assert validate.front_matter_warnings(tmp_path) == []

    def test_a_non_markdown_conversion_is_not_scanned(self, tmp_path):
        """``.txt``/``.csv`` conversions are not asked to carry a block.

        A pdftotext dump whose first line happens to be ``---`` is not a damaged
        source, and no writer puts front matter in one.
        """
        _sources(tmp_path, dump__txt=DAMAGED, table__csv=DAMAGED)
        assert validate.front_matter_warnings(tmp_path) == []

    def test_an_uncited_source_is_still_reported(self, tmp_path):
        """No ``facts/candidates.csv`` at all, and the file is still found.

        The rest of validate.py reaches sources through the facts and pages that
        cite them. De-duplication does not — it walks the tree — so a source no
        fact cites is exactly as able to be re-imported into a duplicate.
        """
        _sources(tmp_path, damaged__md=DAMAGED)
        assert not (tmp_path / "facts").exists()
        assert len(validate.front_matter_warnings(tmp_path)) == 1

    def test_a_nested_source_is_reported(self, tmp_path):
        (tmp_path / "sources" / "2020").mkdir(parents=True)
        (tmp_path / "sources" / "2020" / "damaged.md").write_text(DAMAGED, encoding="utf-8")
        warnings = validate.front_matter_warnings(tmp_path)
        assert [message.split(":")[0] for _tag, message in warnings] == ["sources/2020/damaged.md"]

    def test_run_sources_are_reported_too(self, tmp_path):
        """``runs/sources/`` is a source root here as it is everywhere else.

        validate.py already accepts both prefixes for a fact's source, so scanning
        only ``sources/`` would leave half the tree unwatched.
        """
        (tmp_path / "runs" / "sources").mkdir(parents=True)
        (tmp_path / "runs" / "sources" / "damaged.md").write_text(DAMAGED, encoding="utf-8")
        warnings = validate.front_matter_warnings(tmp_path)
        assert [message.split(":")[0] for _tag, message in warnings] == ["runs/sources/damaged.md"]

    def test_the_order_is_the_shared_enumerator_s(self, tmp_path):
        """Deterministic, and in the order every other sources/ walker uses.

        Expected from ``source_files`` rather than restated, so the two cannot
        drift: a copy of today's ordering here would go quietly wrong the moment
        the enumerator's did.
        """
        _sources(tmp_path, b__md=DAMAGED, a__md=DAMAGED)
        (tmp_path / "runs" / "sources").mkdir(parents=True)
        (tmp_path / "runs" / "sources" / "c.md").write_text(DAMAGED, encoding="utf-8")
        expected = [p.relative_to(tmp_path).as_posix() for p in source_files(tmp_path)]
        assert len(expected) == 3, "fixture is not what the enumerator sees"
        assert [
            message.split(":")[0] for _tag, message in validate.front_matter_warnings(tmp_path)
        ] == expected

    def test_a_hidden_path_is_not_a_source(self, tmp_path):
        """``sources/.obsidian/…`` and ``sources/.hidden.md`` are not sources (#67).

        ``factlog sources``, ``sync`` and ``export`` all skip them through one
        enumerator. A private glob here would warn about editor state and a
        ``.git`` checkout under sources/, which no re-import can ever duplicate.
        """
        (tmp_path / "sources" / ".obsidian").mkdir(parents=True)
        (tmp_path / "sources" / ".obsidian" / "workspace.md").write_text(DAMAGED, encoding="utf-8")
        (tmp_path / "sources" / ".hidden.md").write_text(DAMAGED, encoding="utf-8")
        assert source_files(tmp_path) == [], "fixture is visible to the enumerator"
        assert validate.front_matter_warnings(tmp_path) == []

    def test_a_kb_with_no_source_directories_reports_nothing(self, tmp_path):
        """A missing ``sources/`` is already an error elsewhere, not a crash here."""
        assert validate.front_matter_warnings(tmp_path) == []


class TestTheReasonIsAccurate:
    def test_a_block_past_the_cap_is_not_called_unclosed(self, tmp_path):
        """The fence is in the file; the search stopped before reaching it.

        Unreachable in practice — it takes a megabyte of front matter — but the two
        cases are indistinguishable to the reader, so the message is the only place
        the difference survives. Telling this operator to restore a ``---`` would
        send them looking for something already there.
        """
        pad = "x" * FRONT_MATTER_MAX_CHARS
        _sources(tmp_path, huge__md=f'---\ntitle: "T"\nauthors: {pad}\n---\n\nBody.\n')
        warnings = validate.front_matter_warnings(tmp_path)
        assert len(warnings) == 1
        _tag, message = warnings[0]
        assert FRONT_MATTER_UNSCANNED in message
        assert FRONT_MATTER_UNCLOSED not in message

    def test_the_warning_says_what_it_costs(self, tmp_path):
        """The remedy is not obvious from "no front matter", which is why #422 exists.

        A user reading only the reason would learn the file is malformed, not that
        it has silently left de-duplication — which is the part that produces the
        duplicate they will otherwise find later.
        """
        _sources(tmp_path, damaged__md=DAMAGED)
        assert validate.FRONT_MATTER_CONSEQUENCE in validate.front_matter_warnings(tmp_path)[0][1]
        assert "duplicate" in validate.FRONT_MATTER_CONSEQUENCE


class TestItStaysAWarning:
    """Reported, never fatal.

    An unclosed block leaves the KB entirely valid — the facts, the refs and the
    schema all still hold — and every KB that has one such file would start failing
    if this were an error. The whole point is to make a cost visible early, not to
    add a new way to stop.
    """

    @staticmethod
    def _run(tmp_path, monkeypatch, capsys, errors):
        monkeypatch.setattr(validate, "validate", lambda root: errors)
        monkeypatch.setattr("sys.argv", ["validate.py", str(tmp_path)])
        code = validate.main()
        return code, capsys.readouterr().out

    def test_a_damaged_source_alone_still_passes(self, tmp_path, monkeypatch, capsys):
        _sources(tmp_path, damaged__md=DAMAGED)
        code, out = self._run(tmp_path, monkeypatch, capsys, [])
        assert code == 0
        assert "validation passed" in out
        assert "warning: no_closing_fence: sources/damaged.md" in out

    def test_the_warning_survives_a_failing_run(self, tmp_path, monkeypatch, capsys):
        """Printed before the verdict, so a failure does not swallow it."""
        _sources(tmp_path, damaged__md=DAMAGED)
        code, out = self._run(tmp_path, monkeypatch, capsys, ["missing directory: pages/"])
        assert code == 1
        assert "warning: no_closing_fence: sources/damaged.md" in out
        assert out.index("no_closing_fence") < out.index("validation failed")

    def test_a_clean_kb_prints_no_warning_line(self, tmp_path, monkeypatch, capsys):
        _sources(tmp_path, intact__md=INTACT)
        code, out = self._run(tmp_path, monkeypatch, capsys, [])
        assert code == 0
        assert "warning" not in out

    def test_the_tag_does_not_assert_the_stronger_reason(self):
        """``no_closing_fence`` holds for both reported reasons; ``unclosed`` does not.

        The tag is what a script greps for, so it has to be true of the cap case as
        well — and both reason strings say those exact words.
        """
        for reason in validate.WARNED_FRONT_MATTER_ABSENCES:
            assert "no closing fence" in reason


def _fence_deleted(identity_key: str) -> str:
    """A writer's output for one integration with its opening ``---`` deleted.

    Built from the identity key itself so every entry of ``IDENTITY_KEYS_BY_SOURCE``
    is exercised by the same shape, and a key added there is covered here without a
    new fixture. The closing fence stays, matching what a human who removes only the
    opening line leaves behind.
    """
    return f'{identity_key}: "X123"\ntitle: "A paper"\n---\n\nAbstract.\n'


def _tags(warnings) -> list[str]:
    return [tag for tag, _message in warnings]


class TestADeletedOpeningFenceIsReported:
    """#445: the far side of #422 — a source whose *opening* ``---`` a human deleted.

    It reads as ``no opening fence``, the same reason an ingest conversion or a
    hand-written note carries, so the absence alone cannot warn (that is what #422
    left out on purpose). The identity key at column 0 is what separates it.
    """

    def test_a_source_with_its_opening_fence_deleted_is_reported(self, tmp_path):
        _sources(tmp_path, damaged__md=OPENING_DELETED)
        warnings = validate.front_matter_warnings(tmp_path)
        assert len(warnings) == 1
        tag, message = warnings[0]
        assert tag == "no_opening_fence"
        assert message.startswith("sources/damaged.md: ")

    def test_the_reported_reason_is_the_missing_opening_fence(self, tmp_path):
        """The message carries the reader's own reason, not a restatement of it."""
        _sources(tmp_path, damaged__md=OPENING_DELETED)
        _tag, message = validate.front_matter_warnings(tmp_path)[0]
        assert FRONT_MATTER_NO_OPENING_FENCE in message

    def test_the_warning_names_the_key_it_saw(self, tmp_path):
        """An observation, so it says which key — not just that the file looks off."""
        _sources(tmp_path, damaged__md=OPENING_DELETED)
        _tag, message = validate.front_matter_warnings(tmp_path)[0]
        assert "openalex_id" in message

    def test_the_warning_says_what_it_costs(self, tmp_path):
        """Same cost as the closing-fence case — a silent duplicate on re-import."""
        _sources(tmp_path, damaged__md=OPENING_DELETED)
        _tag, message = validate.front_matter_warnings(tmp_path)[0]
        assert validate.FRONT_MATTER_CONSEQUENCE in message

    def test_every_integration_s_identity_key_is_recognised(self, tmp_path):
        """Each key in ``IDENTITY_KEYS_BY_SOURCE`` triggers the warning.

        Derived from the writers' own map so a mutant that hardcodes a subset (say,
        only ``openalex_id``) is caught by whichever key it dropped. If a fifth
        integration is added there, this fails until it is covered here too.
        """
        assert IDENTITY_KEYS_BY_SOURCE, "the writers' identity map is empty"
        for key in IDENTITY_KEYS_BY_SOURCE.values():
            root = tmp_path / key
            _sources(root, damaged__md=_fence_deleted(key))
            warnings = validate.front_matter_warnings(root)
            assert _tags(warnings) == ["no_opening_fence"], f"{key} not recognised"
            assert key in warnings[0][1]

    def test_the_first_non_empty_line_is_what_is_read(self, tmp_path):
        """A blank line left where the ``---`` was does not hide the key.

        Removing only the three dashes can leave the trailing newline, so the first
        *line* is empty and the key is on the second. A first-line-only check would
        miss this; "first non-empty line" does not.
        """
        _sources(tmp_path, damaged__md="\n" + OPENING_DELETED)
        assert _tags(validate.front_matter_warnings(tmp_path)) == ["no_opening_fence"]


class TestADeletedOpeningFenceIsNotOverReported:
    """The counterexamples — each must be silent for the *right* reason.

    Every fixture here reads as ``no opening fence`` too (verified below), so a mutant
    that warns on that reason alone would light all of them up. What keeps them quiet
    is that their first non-empty line is not an importer identity key.
    """

    def test_an_ingest_conversion_is_not_reported(self, tmp_path):
        """Opens with the HTML provenance comment the converter writes, not a key."""
        conv = "<!-- ingested-by-factlog | source: report.pdf | converter: pandoc | date: 2026 -->\n\nText.\n"
        _sources(tmp_path, converted__md=conv)
        assert validate.front_matter_warnings(tmp_path) == []
        # …and it is silent because it has no key first, not because it somehow has a
        # fence: the reader still calls it no-opening-fence, the warned-on reason.
        assert validate.front_matter_absence(tmp_path / "sources" / "converted.md") == \
            FRONT_MATTER_NO_OPENING_FENCE

    def test_a_prose_note_is_not_reported(self, tmp_path):
        """A hand-written note opens with a heading, not a key."""
        _sources(tmp_path, note__md="# My note\n\nSome thoughts on a paper.\n")
        assert validate.front_matter_warnings(tmp_path) == []
        assert validate.front_matter_absence(tmp_path / "sources" / "note.md") == \
            FRONT_MATTER_NO_OPENING_FENCE

    def test_an_identifier_in_the_body_is_not_reported(self, tmp_path):
        """The #419 false positive: a note that *cites* a paper by id in its body.

        This is why the signal is the first line and not "an identifier anywhere":
        the demo corpus measured 51% of real sources carrying a ``doi:`` line in
        their prose, and warning on those would bury the one damaged file.
        """
        body = "# Reading note\n\nThe key claim (doi: 10.1234/x, pmid: 42) is strong.\n"
        _sources(tmp_path, note__md=body)
        assert validate.front_matter_warnings(tmp_path) == []

    def test_an_identity_key_below_the_first_line_is_not_reported(self, tmp_path):
        """A key on a later line is body text, not a deleted-fence opening.

        The narrower converse of the test above: even a bare ``pmid:`` line, if it is
        not what the file opens with, is not the shape of a deleted opening fence.
        """
        _sources(tmp_path, note__md="Notes on retractions.\n\npmid: 12345678\n")
        assert validate.front_matter_warnings(tmp_path) == []

    def test_an_intact_source_is_not_reported(self, tmp_path):
        """A file that still has its opening ``---`` has a readable block, not an absence."""
        _sources(tmp_path, intact__md=INTACT)
        assert validate.front_matter_warnings(tmp_path) == []
        assert validate.front_matter_absence(tmp_path / "sources" / "intact.md") is None

    def test_an_unrelated_yaml_like_first_line_is_not_reported(self, tmp_path):
        """A note that opens with some *other* ``key:`` line is not an importer file.

        The signal is the writers' own identity keys, not any ``key: value`` shape,
        so a user's ``status: draft`` header does not read as a deleted fence.
        """
        _sources(tmp_path, note__md="status: draft\ntitle: my own note\n")
        assert validate.front_matter_warnings(tmp_path) == []


class TestADeletedOpeningFenceStaysAWarning:
    """Reported through the same never-fatal channel as #422, under its own tag."""

    @staticmethod
    def _run(tmp_path, monkeypatch, capsys, errors):
        monkeypatch.setattr(validate, "validate", lambda root: errors)
        monkeypatch.setattr("sys.argv", ["validate.py", str(tmp_path)])
        code = validate.main()
        return code, capsys.readouterr().out

    def test_it_prints_under_its_own_tag_and_still_passes(self, tmp_path, monkeypatch, capsys):
        _sources(tmp_path, damaged__md=OPENING_DELETED)
        code, out = self._run(tmp_path, monkeypatch, capsys, [])
        assert code == 0
        assert "validation passed" in out
        assert "warning: no_opening_fence: sources/damaged.md" in out
        # Not the closing-fence tag: the two damage shapes are grepped apart.
        assert "no_closing_fence" not in out

    def test_the_warning_survives_a_failing_run(self, tmp_path, monkeypatch, capsys):
        _sources(tmp_path, damaged__md=OPENING_DELETED)
        code, out = self._run(tmp_path, monkeypatch, capsys, ["missing directory: pages/"])
        assert code == 1
        assert "warning: no_opening_fence: sources/damaged.md" in out
        assert out.index("no_opening_fence") < out.index("validation failed")


class TestTheOpeningKeyProbe:
    """``_opening_identity_key`` in isolation — the unit the signal rests on."""

    def test_it_returns_the_key_a_damaged_source_opens_with(self, tmp_path):
        p = tmp_path / "damaged.md"
        p.write_text(OPENING_DELETED, encoding="utf-8")
        assert validate._opening_identity_key(p) == "openalex_id"

    def test_it_returns_none_for_a_prose_first_line(self, tmp_path):
        p = tmp_path / "note.md"
        p.write_text("# Heading\n\narxiv_id: 1706.03762\n", encoding="utf-8")
        assert validate._opening_identity_key(p) is None

    def test_it_matches_the_key_at_column_zero_only(self, tmp_path):
        """An indented ``  pmid:`` is body, not a front-matter key — no writer indents."""
        p = tmp_path / "indented.md"
        p.write_text("  pmid: 12345678\n---\n", encoding="utf-8")
        assert validate._opening_identity_key(p) is None

    def test_the_probe_regex_covers_exactly_the_writers_keys(self):
        """The alternation is built from the map, so the two cannot drift apart."""
        for key in IDENTITY_KEYS_BY_SOURCE.values():
            assert validate._OPENING_IDENTITY_KEY_RE.match(f"{key}: value")
        assert validate._OPENING_IDENTITY_KEY_RE.match("title: not an identity key") is None

    def test_an_unreadable_file_probes_to_none(self, tmp_path):
        """Undecodable bytes are 'no key', matching the reader's own catch."""
        p = tmp_path / "binary.md"
        p.write_bytes(b"\xff\xfe\x00\x01 not utf-8")
        assert validate._opening_identity_key(p) is None
