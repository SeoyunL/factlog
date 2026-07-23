# SPDX-License-Identifier: Apache-2.0
"""Unit tests for BibTeX export core (front matter reader + formatter)."""
from __future__ import annotations

from factlog.bibtex import (
    is_annotation_source,
    parse_front_matter,
    read_front_matter,
    safe_cite_key,
    to_bibtex,
)

FM_TEXT = (
    '---\n'
    'zotero_key: "ABCD"\n'
    'item_type: "journalArticle"\n'
    'title: "Omega-3 & COPD: a \\"study\\""\n'
    'authors: ["Matsuyama W", "Mitsuyama H"]\n'
    'year: "2005"\n'
    'journal: "Chest"\n'
    'doi: "10.1378/x"\n'
    'pmid: "16354850"\n'
    'retracted: true\n'
    '---\n\n# body\n'
)


class TestParse:
    def test_reads_scalars_lists_bools(self):
        fm = parse_front_matter(FM_TEXT)
        assert fm["zotero_key"] == "ABCD"
        assert fm["authors"] == ["Matsuyama W", "Mitsuyama H"]
        assert fm["title"] == 'Omega-3 & COPD: a "study"'  # unescaped
        assert fm["retracted"] is True

    def test_no_front_matter(self):
        assert parse_front_matter("# just a body\n") == {}

    def test_reads_file(self, tmp_path):
        f = tmp_path / "s.md"
        f.write_text(FM_TEXT, encoding="utf-8")
        assert read_front_matter(f)["journal"] == "Chest"

    def test_annotation_marker(self):
        assert is_annotation_source({"source_kind": "annotations"}) is True
        assert is_annotation_source({"item_type": "book"}) is False


class TestCiteKey:
    def test_sanitizes(self):
        assert safe_cite_key("matsuyama-2005-omega3") == "matsuyama-2005-omega3"
        assert safe_cite_key("김무성 2005!") == "2005"  # non-ascii collapsed
        assert safe_cite_key("!!!") == "ref"


class TestToBibtex:
    def test_full_entry(self):
        out = to_bibtex(parse_front_matter(FM_TEXT), "matsuyama-2005")
        assert out.startswith("@article{matsuyama-2005,")
        assert "author = {Matsuyama W and Mitsuyama H}," in out
        assert r'title = {Omega-3 \& COPD: a "study"},' in out  # & escaped, quotes literal
        assert "year = {2005}," in out
        assert "journal = {Chest}," in out
        assert "doi = {10.1378/x}," in out
        assert "note = {PMID: 16354850}," in out
        assert out.rstrip().endswith("}")

    def test_entry_type_mapping(self):
        assert to_bibtex({"item_type": "preprint", "title": "T"}, "k").startswith("@misc{")
        assert to_bibtex({"item_type": "book", "title": "T"}, "k").startswith("@book{")
        assert to_bibtex({"item_type": "weird", "title": "T"}, "k").startswith("@misc{")
        assert to_bibtex({"title": "T"}, "k").startswith("@misc{")

    def test_empty_fields_omitted(self):
        out = to_bibtex({"item_type": "book", "title": "T"}, "k")
        assert "author" not in out and "doi" not in out and "note" not in out

    def test_escaping_special_chars(self):
        out = to_bibtex({"title": "a_b % c # d $ e"}, "k")
        assert r"\_" in out and r"\%" in out and r"\#" in out and r"\$" in out

    def test_non_ascii_kept(self):
        out = to_bibtex({"title": "제목", "authors": ["김 무성"]}, "k")
        assert "제목" in out and "김 무성" in out


class TestIdentifierDigitFolding:
    """`doi` and the `PMID:` note are folded on the way out (#428).

    The BibTeX twin of `test_csl.py::TestIdentifierDigitFolding`, kept as its own
    class rather than shared: the two exporters reach the same two folds by
    separate code paths, and a fix applied to only one of them has to fail
    somewhere.
    """

    def test_full_width_doi_prefix_is_folded(self):
        out = to_bibtex({"doi": "10.１２３４/abc"}, "k")
        assert "doi = {10.1234/abc}," in out

    def test_full_width_pmid_in_the_note_is_folded(self):
        out = to_bibtex({"pmid": "１２３４５６７８"}, "k")
        assert "note = {PMID: 12345678}," in out

    def test_doi_suffix_is_not_folded(self):
        out = to_bibtex({"doi": "10.１２３４/abc１"}, "k")
        assert "doi = {10.1234/abc１}," in out

    def test_doi_case_is_preserved(self):
        # `fold_doi_prefix`, not the lowercasing `normalize_cross_id` join key —
        # the assertion that separates the two here as it does in the CSL twin.
        out = to_bibtex({"doi": "10.１３７８/CHEST.128"}, "k")
        assert "doi = {10.1378/CHEST.128}," in out

    def test_an_unrecognised_wrapper_is_exported_as_stored(self):
        out = to_bibtex({"doi": "https://doi.org/10.１２３４/abc", "pmid": "pmid:１２３"}, "k")
        assert "doi = {https://doi.org/10.１２３４/abc}," in out
        assert "note = {PMID: pmid:１２３}," in out

    def test_field_order_is_unchanged(self):
        # `doi` was lifted out of the loop it shared with title/year/journal so it
        # could be folded. Order is part of this module's output, so pin it: an
        # existing `.bib` must still diff clean.
        out = to_bibtex(
            {"authors": ["A B"], "title": "T", "year": "2005", "journal": "Chest",
             "doi": "10.1/x", "pmid": "163"},
            "k",
        )
        names = [line.split(" = ", 1)[0].strip() for line in out.splitlines()
                 if " = {" in line]
        assert names == ["author", "title", "year", "journal", "doi", "note"]

    def test_absent_identifiers_emit_no_field(self):
        out = to_bibtex({"title": "T"}, "k")
        assert "doi" not in out and "note" not in out
