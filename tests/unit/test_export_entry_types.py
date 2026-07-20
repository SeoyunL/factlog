# SPDX-License-Identifier: Apache-2.0
"""Work-type resolution across all four integrations (#384).

Each integration records the work type under a different front-matter key, but
both exporters used to read only Zotero's ``item_type`` — so every OpenAlex,
arXiv and PubMed record exported as ``@misc``/``"document"``, and nine of a
25-record KB came out as ``@misc`` *carrying a* ``journal`` *field*, which is
not a valid standard-BibTeX pairing.

Three things are pinned here, because each failed differently:

* the *keys* (`TestWritersStillUseTheKeysWeRead`) — driven through the real
  ``SourceWriter``s, so renaming a key in a writer fails here instead of
  silently degrading the export again;
* the *values* (`TestTypeMaps`) — every mapping asserted against an explicit
  expected pair, so an entry cannot be added or neutered without a test moving;
* the *export path* (`TestExportPathOnDisk`) — through files on disk and
  ``cli.main``, because the in-memory helpers skip the front-matter read that
  truncates at 4096 bytes.
"""
from __future__ import annotations

import json
import re
from datetime import date

import pytest

from factlog.bibtex import _ENTRY_TYPES, parse_front_matter, read_front_matter, to_bibtex
from factlog.csl import _CSL_TYPES, to_csl
from factlog.export_types import resolve_source_type, should_promote_to_journal_type
from factlog.integrations.arxiv.source_writer import ArxivSourceWriter
from factlog.integrations.arxiv.work_parser import ParsedArxivWork
from factlog.integrations.openalex.api_client import WORK_TYPES
from factlog.integrations.openalex.source_writer import OpenAlexSourceWriter
from factlog.integrations.openalex.work_parser import ParsedWork
from factlog.integrations.pubmed.source_writer import PubMedSourceWriter
from factlog.integrations.pubmed.work_parser import ParsedPubMedWork
from factlog.integrations.zotero.item_parser import parse_item
from factlog.integrations.zotero.source_writer import SourceWriter as ZoteroSourceWriter

# --------------------------------------------------------------------------
# Records built by the real writers, so the keys under test are the keys that
# actually reach a KB.
# --------------------------------------------------------------------------


def _zotero_md(item_type: str = "journalArticle", journal: str = "Chest") -> str:
    parsed = parse_item({
        "key": "ABCD1234",
        "data": {
            "itemType": item_type,
            "title": "A Zotero record",
            "creators": [{"creatorType": "author", "lastName": "Kim", "firstName": "M"}],
            "date": "2005-03-01",
            "publicationTitle": journal,
            "DOI": "10.1378/chest.x",
        },
    })
    return ZoteroSourceWriter().render(parsed)


def _openalex_md(work_type: str = "article", journal: str | None = "The Lancet") -> str:
    parsed = ParsedWork(
        openalex_id="W2038858046",
        title="Ileal-lymphoid-nodular hyperplasia",
        authors=("A J Wakefield",),
        year=1998,
        journal=journal,
        doi="10.1016/s0140-6736(97)11096-0",
        pmid="9500320",
        work_type=work_type,
        abstract="An OpenAlex record.",
    )
    return OpenAlexSourceWriter().render(parsed)


def _arxiv_md(journal_ref: str | None = None, n_authors: int = 1) -> str:
    parsed = ParsedArxivWork(
        arxiv_id="2012.05876",
        version=1,
        title="Neurosymbolic AI: the 3rd wave",
        authors=tuple(f"Author {i} of a large collaboration" for i in range(n_authors)),
        abstract="An arXiv deposit.",
        primary_category="cs.AI",
        categories=("cs.AI",),
        submitted=date(2020, 12, 10),
        last_updated=date(2020, 12, 10),
        journal_ref=journal_ref,
    )
    return ArxivSourceWriter().render(parsed)


def _pubmed_md() -> str:
    parsed = ParsedPubMedWork(
        pmid="16354850",
        title="Omega-3 fatty acids in COPD",
        authors=("Matsuyama W",),
        journal="Chest",
        year=2005,
        doi="10.1378/chest.128.6.3817",
        abstract="A PubMed record.",
    )
    return PubMedSourceWriter().render(parsed)


def _zotero_fm(item_type: str = "journalArticle", journal: str = "Chest") -> dict:
    return parse_front_matter(_zotero_md(item_type, journal))


def _openalex_fm(work_type: str = "article", journal: str | None = "The Lancet") -> dict:
    return parse_front_matter(_openalex_md(work_type, journal))


def _arxiv_fm(journal_ref: str | None = None) -> dict:
    return parse_front_matter(_arxiv_md(journal_ref))


def _pubmed_fm() -> dict:
    return parse_front_matter(_pubmed_md())


ALL_SOURCES = {
    "zotero": _zotero_fm,
    "openalex": _openalex_fm,
    "arxiv": _arxiv_fm,
    "pubmed": _pubmed_fm,
}

# --------------------------------------------------------------------------
# The expected mapping, stated once. `TestTypeMaps` drives every row through
# the public exporters, so neutering a row in either map fails a named test.
# --------------------------------------------------------------------------

# Zotero itemType -> (BibTeX entry type, CSL type)
ZOTERO_EXPECTED = {
    "journalArticle": ("article", "article-journal"),
    "magazineArticle": ("article", "article-magazine"),
    "newspaperArticle": ("article", "article-newspaper"),
    "conferencePaper": ("inproceedings", "paper-conference"),
    "book": ("book", "book"),
    "bookSection": ("incollection", "chapter"),
    "encyclopediaArticle": ("incollection", "entry-encyclopedia"),
    "dictionaryEntry": ("incollection", "entry-dictionary"),
    "report": ("techreport", "report"),
    "thesis": ("phdthesis", "thesis"),
    "preprint": ("misc", "article"),
}

# OpenAlex work type -> (BibTeX entry type, CSL type)
OPENALEX_EXPECTED = {
    "article": ("article", "article-journal"),
    "review": ("article", "article-journal"),
    "book-review": ("article", "article-journal"),
    "letter": ("article", "article-journal"),
    "editorial": ("article", "article-journal"),
    "erratum": ("article", "article-journal"),
    "retraction": ("article", "article-journal"),
    "data-paper": ("article", "article-journal"),
    "conference-paper": ("inproceedings", "paper-conference"),
    "book-chapter": ("incollection", "chapter"),
    "book-section": ("incollection", "chapter"),
    "reference-entry": ("incollection", "entry-encyclopedia"),
    "dissertation": ("phdthesis", "thesis"),
    "report-component": ("techreport", "report"),
    "book": ("book", "book"),
    "report": ("techreport", "report"),
    "preprint": ("misc", "article"),
    # Standard BibTeX has no @dataset/@software; CSL does, so these diverge by
    # design — the BibTeX side is the coarser vocabulary, never a contradiction.
    "dataset": ("misc", "dataset"),
    "software": ("misc", "software"),
}


def _entry_of(out: str) -> str:
    return out.split("{", 1)[0].lstrip("@")


class TestWritersStillUseTheKeysWeRead:
    """The premise of the fix: each writer emits the key the resolver probes."""

    def test_zotero_emits_item_type(self):
        assert _zotero_fm()["item_type"] == "journalArticle"

    def test_openalex_emits_type_and_its_provenance_marker(self):
        fm = _openalex_fm()
        assert fm["type"] == "article"
        # `type` is trusted only alongside this marker; see TestResolveSourceType.
        assert fm["imported_from"] == "openalex"

    def test_arxiv_emits_preprint_flag(self):
        assert _arxiv_fm()["preprint"] is True

    def test_pubmed_emits_no_type_key_only_journal(self):
        fm = _pubmed_fm()
        assert "item_type" not in fm and "type" not in fm and "preprint" not in fm
        assert fm["journal"] == "Chest"


class TestResolveSourceType:
    def test_probes_each_integrations_key(self):
        assert resolve_source_type(_zotero_fm()) == "journalArticle"
        assert resolve_source_type(_openalex_fm()) == "article"
        assert resolve_source_type(_arxiv_fm()) == "preprint"
        # PubMed answers no key; the `journal` inference is a separate decision.
        assert resolve_source_type(_pubmed_fm()) is None

    def test_item_type_is_probed_first(self):
        fm = {"item_type": "book", "type": "article",
              "imported_from": "openalex", "preprint": True}
        assert resolve_source_type(fm) == "book"

    def test_type_beats_the_preprint_flag(self):
        fm = {"type": "article", "imported_from": "openalex", "preprint": True}
        assert resolve_source_type(fm) == "article"

    def test_bare_type_is_trusted_only_on_an_openalex_record(self):
        """`type` is the ledger's RESERVED key for the source name (#73), so a
        front-matter `type` is read only where the OpenAlex writer put it."""
        assert resolve_source_type({"type": "article"}) is None
        assert resolve_source_type({"type": "article", "imported_from": "zotero"}) is None
        assert resolve_source_type(
            {"type": "article", "imported_from": "openalex"}) == "article"

    def test_blank_and_non_string_keys_fall_through(self):
        fm = {"item_type": "  ", "type": "article", "imported_from": "openalex"}
        assert resolve_source_type(fm) == "article"
        assert resolve_source_type({"item_type": 7, "preprint": True}) == "preprint"
        # `preprint: false` is not an answer, it is the absence of one.
        assert resolve_source_type({"preprint": False}) is None
        assert resolve_source_type({}) is None


class TestShouldPromoteToJournalType:
    """The inference fires only where nothing was declared (the #384 narrowing)."""

    def test_fires_only_when_no_key_declared_a_type(self):
        assert should_promote_to_journal_type({"journal": "Chest"}, None) is True
        assert should_promote_to_journal_type({}, None) is False

    def test_never_overrides_a_declared_type(self):
        # Zotero fills `journal` from publicationTitle for ANY item type, so a
        # magazine article names a journal without being one.
        assert should_promote_to_journal_type(
            {"journal": "The Economist"}, "magazineArticle") is False
        # And an arXiv deposit stays a preprint once published (#60).
        assert should_promote_to_journal_type({"journal": "Nature"}, "preprint") is False


class TestTypeMaps:
    """Every mapping asserted against an expected pair, via the public exporters."""

    def test_maps_cover_exactly_the_expected_vocabulary(self):
        expected = set(ZOTERO_EXPECTED) | set(OPENALEX_EXPECTED)
        assert set(_ENTRY_TYPES) == expected
        assert set(_CSL_TYPES) == expected

    @pytest.mark.parametrize(("item_type", "expected"), sorted(ZOTERO_EXPECTED.items()))
    def test_zotero_vocabulary(self, item_type, expected):
        fm = {"item_type": item_type, "title": "T"}
        assert (_entry_of(to_bibtex(fm, "k")), to_csl(fm, "k")["type"]) == expected

    @pytest.mark.parametrize(("work_type", "expected"), sorted(OPENALEX_EXPECTED.items()))
    def test_openalex_vocabulary(self, work_type, expected):
        fm = {"type": work_type, "imported_from": "openalex", "title": "T"}
        assert (_entry_of(to_bibtex(fm, "k")), to_csl(fm, "k")["type"]) == expected

    def test_openalex_keys_are_real_openalex_work_types(self):
        """The vocabulary has one authority (api_client.WORK_TYPES); a typo here
        would be a dead map entry that no record can ever match."""
        assert set(OPENALEX_EXPECTED) <= set(WORK_TYPES)

    def test_unknown_type_still_falls_back(self):
        fm = {"item_type": "holotape", "title": "T"}
        assert _entry_of(to_bibtex(fm, "k")) == "misc"
        assert to_csl(fm, "k")["type"] == "document"


class TestZoteroOutputIsUnchanged:
    """The fix targets the other three sources; Zotero records must not move.

    `journal` is filled from `publicationTitle` for every Zotero item type, so an
    inference that ignored the declared type re-typed magazine and newspaper
    articles as journal articles — worse than the old default, since CSL has
    dedicated types for both.
    """

    @pytest.mark.parametrize(("item_type", "entry", "csl"), [
        ("journalArticle", "article", "article-journal"),
        ("magazineArticle", "article", "article-magazine"),
        ("newspaperArticle", "article", "article-newspaper"),
        ("preprint", "misc", "article"),
        ("holotape", "misc", "document"),  # unmapped: still the default
    ])
    def test_declared_type_wins_over_the_journal_field(self, item_type, entry, csl):
        fm = _zotero_fm(item_type)
        assert fm["journal"]  # the field that used to hijack the type
        assert _entry_of(to_bibtex(fm, "k")) == entry
        assert to_csl(fm, "k")["type"] == csl


class TestBibtexEntryTypes:
    def test_each_integration_gets_a_typed_entry(self):
        assert _entry_of(to_bibtex(_zotero_fm(), "k")) == "article"
        assert _entry_of(to_bibtex(_openalex_fm(), "k")) == "article"
        assert _entry_of(to_bibtex(_pubmed_fm(), "k")) == "article"
        # An arXiv deposit is a preprint; #60 says it stays one.
        assert _entry_of(to_bibtex(_arxiv_fm(), "k")) == "misc"

    def test_pubmed_is_typed_purely_from_its_journal(self):
        out = to_bibtex(_pubmed_fm(), "k")
        assert out.startswith("@article{") and "journal = {Chest}," in out

    def test_misc_records_its_venue_as_howpublished(self):
        """@misc has no `journal` field, so the venue would be dropped with a
        warning; `howpublished` keeps it without retyping the entry."""
        out = to_bibtex(_arxiv_fm(journal_ref="Nature 585, 357 (2020)"), "k")
        assert out.startswith("@misc{")
        assert "howpublished = {Nature 585, 357 (2020)}," in out
        assert "journal = " not in out

    def test_no_misc_entry_ever_carries_a_journal_field(self):
        """The defect's signature: 9/25 entries were @misc *with* a journal."""
        variants = [build() for build in ALL_SOURCES.values()]
        variants += [
            _zotero_fm("preprint"), _zotero_fm("magazineArticle"), _zotero_fm("holotape"),
            _openalex_fm(work_type="preprint"), _openalex_fm(work_type="dataset"),
            _arxiv_fm(journal_ref="Nature 585, 357 (2020)"),
        ]
        offenders = [
            fm for fm in variants
            if _entry_of(to_bibtex(fm, "k")) == "misc" and "journal = " in to_bibtex(fm, "k")
        ]
        assert offenders == []


class TestCslTypes:
    def test_each_integration_gets_a_typed_item(self):
        assert to_csl(_zotero_fm(), "k")["type"] == "article-journal"
        assert to_csl(_openalex_fm(), "k")["type"] == "article-journal"
        assert to_csl(_pubmed_fm(), "k")["type"] == "article-journal"
        assert to_csl(_arxiv_fm(), "k")["type"] == "article"  # preprint

    def test_no_document_item_ever_carries_a_container_title(self):
        for build in ALL_SOURCES.values():
            item = to_csl(build(), "k")
            assert not (item["type"] == "document" and item.get("container-title"))


class TestExportersAgreeAfterFallbacks:
    """Consistency checked on *resolved output*, not just the static maps.

    The two exporters previously applied the `journal` inference on different
    conditions (`entry == "misc"` vs `csl_type == "document"`), which a static
    map comparison could not see. These cases run the whole path.
    """

    _EQUIVALENT = {
        ("article", "article-journal"), ("article", "article-magazine"),
        ("article", "article-newspaper"), ("inproceedings", "paper-conference"),
        ("book", "book"), ("incollection", "chapter"),
        ("incollection", "entry-encyclopedia"), ("incollection", "entry-dictionary"),
        ("techreport", "report"), ("phdthesis", "thesis"),
        ("misc", "article"), ("misc", "document"),
        ("misc", "dataset"), ("misc", "software"),
    }

    @pytest.mark.parametrize("fm", [
        _zotero_fm(), _zotero_fm("magazineArticle"), _zotero_fm("preprint"),
        _openalex_fm(), _openalex_fm(work_type="conference-paper"),
        _openalex_fm(work_type="dataset"),
        _arxiv_fm(), _arxiv_fm(journal_ref="Nature 585, 357 (2020)"),
        _pubmed_fm(), {"title": "no type at all"},
    ])
    def test_resolved_pair_is_never_a_disagreement(self, fm):
        pair = (_entry_of(to_bibtex(fm, "k")), to_csl(fm, "k")["type"])
        assert pair in self._EQUIVALENT

    def test_arxiv_preprint_is_a_preprint_in_both_formats(self):
        """A published deposit keeps its preprint typing on both sides — the
        asymmetry a BibTeX-only promotion used to introduce."""
        fm = _arxiv_fm(journal_ref="Nature 585, 357 (2020)")
        assert _entry_of(to_bibtex(fm, "k")) == "misc"
        assert to_csl(fm, "k")["type"] == "article"


class TestExportPathOnDisk:
    """The real path: files on disk, read through `read_front_matter`, via the CLI.

    The in-memory helpers above never exercise the 4096-byte front-matter read,
    which is where a large author list silently costs a record its type.
    """

    @staticmethod
    def _kb(tmp_path, extra: dict[str, str] | None = None):
        sources = tmp_path / "sources"
        sources.mkdir()
        files = {
            "zotero.md": _zotero_md(),
            "openalex.md": _openalex_md(),
            "arxiv.md": _arxiv_md(),
            "pubmed.md": _pubmed_md(),
        }
        files.update(extra or {})
        for name, text in files.items():
            (sources / name).write_text(text, encoding="utf-8")
        return tmp_path

    def _export(self, tmp_path, fmt: str, extra=None) -> str:
        from factlog.cli import main
        kb = self._kb(tmp_path, extra)
        out = tmp_path / f"out.{fmt}"
        assert main(["export", f"--{fmt}", "--target", str(kb), "-o", str(out)]) == 0
        return out.read_text(encoding="utf-8")

    def test_bibtex_distribution_over_a_four_source_kb(self, tmp_path):
        text = self._export(tmp_path, "bibtex")
        entries = sorted(line for line in text.splitlines() if line.startswith("@"))
        assert entries == [
            "@article{openalex,", "@article{pubmed,", "@article{zotero,", "@misc{arxiv,",
        ]

    def test_csl_distribution_over_a_four_source_kb(self, tmp_path):
        items = json.loads(self._export(tmp_path, "csl"))
        assert {i["id"]: i["type"] for i in items} == {
            "zotero": "article-journal", "openalex": "article-journal",
            "pubmed": "article-journal", "arxiv": "article",
        }

    def test_exported_kb_has_no_misc_with_journal(self, tmp_path):
        """The issue's acceptance criterion, asserted on real CLI output."""
        text = self._export(tmp_path, "bibtex", extra={
            "arxiv-published.md": _arxiv_md(journal_ref="Nature 585, 357 (2020)"),
            "zotero-preprint.md": _zotero_md("preprint"),
            "zotero-magazine.md": _zotero_md("magazineArticle", "The Economist"),
        })
        entries = [e for e in re.split(r"(?=^@)", text, flags=re.M) if e.startswith("@")]
        assert len(entries) == 7
        assert [e for e in entries if e.startswith("@misc") and "journal = " in e] == []

    def test_large_author_list_truncates_front_matter(self, tmp_path):
        """Known limitation, pinned so it is not mistaken for a passing case.

        `read_front_matter` reads only the first 4096 bytes, and the arXiv writer
        emits `preprint:` after the single-line `authors:`, so a large
        collaboration pushes the type key out of the window and the record falls
        back to the default type. Raising the window (or moving identity keys
        ahead of `authors`) changes writer output, so it is filed separately
        rather than fixed here; when it is fixed this assertion flips and should
        be updated. The acceptance criterion holds either way.
        """
        path = tmp_path / "big.md"
        text = _arxiv_md(journal_ref="Nature 585, 357 (2020)", n_authors=200)
        path.write_text(text, encoding="utf-8")
        assert len(text.split("---")[1].encode()) > 4096

        fm = read_front_matter(path)
        assert "preprint" not in fm  # the type key fell outside the read window
        # Whatever survives, the invalid pairing must not appear.
        out = to_bibtex(fm, "big")
        assert not (out.startswith("@misc") and "journal = " in out)

    def test_large_author_list_still_exports_without_misc_journal(self, tmp_path):
        text = self._export(tmp_path, "bibtex", extra={
            "big.md": _arxiv_md(journal_ref="Nature 585, 357 (2020)", n_authors=200),
        })
        entries = [e for e in re.split(r"(?=^@)", text, flags=re.M) if e.startswith("@")]
        assert [e for e in entries if e.startswith("@misc") and "journal = " in e] == []
