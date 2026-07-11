# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the pure ``pubmed-mesh`` proposal layer (#173).

These cover the on-disk resolution (PMID read from the provenance ledger, not the
front matter) and the major/minor candidate shaping — no network, no CLI. The
CLI wiring and the live efetch are exercised in ``test_pubmed_mesh_cli.py``.
"""
from __future__ import annotations

import pytest

from factlog.integrations.common.provenance import (
    Provenance,
    SourceRecord,
    sidecar_path,
    write_provenance,
)
from factlog.integrations.pubmed.mesh import MeshHeading, MeshQualifier
from factlog.integrations.pubmed.mesh_suggest import (
    MeshSuggestError,
    build_proposal,
    no_pmid_line,
    no_pmid_porcelain_line,
    proposal_lines,
    proposal_porcelain_lines,
    resolve_pmid,
)

IMPORTED_AT = "2026-01-01T00:00:00+00:00"


def _kb(tmp_path):
    (tmp_path / "sources").mkdir()
    return tmp_path


def _seed(kb, name, *, records):
    """Write a source ``.md`` and its provenance ledger. Returns the slug (no .md)."""
    md = kb / "sources" / f"{name}.md"
    md.write_text(f"---\ntitle: {name}\n---\n# {name}\n")
    if records is not None:
        write_provenance(sidecar_path(md, kb), Provenance(records=records))
    return name


def _pubmed_record(pmid):
    return SourceRecord(type="pubmed", id=pmid, imported_at=IMPORTED_AT, fields={})


# The pre-2010 qualifier-only-major shape (#53): a descriptor flagged N whose
# qualifier is Y is still a MAJOR topic — the case OpenAlex's descriptor-only
# reading drops.
QUALIFIER_ONLY_MAJOR = MeshHeading(
    descriptor="Pulmonary Disease, Chronic Obstructive",
    descriptor_is_major=False,
    qualifiers=(MeshQualifier(name="drug therapy", is_major=True),),
)
DESCRIPTOR_MAJOR = MeshHeading(
    descriptor="Dietary Supplements", descriptor_is_major=True
)
MINOR = MeshHeading(descriptor="Humans", descriptor_is_major=False)


# -- resolve_pmid: where the PMID is read from ------------------------------

class TestResolvePmid:
    def test_reads_pmid_from_the_provenance_ledger(self, tmp_path):
        kb = _kb(tmp_path)
        _seed(kb, "paper", records=[_pubmed_record("32738937")])
        resolution = resolve_pmid(kb, "paper")
        assert resolution.pmid == "32738937"
        assert resolution.slug == "paper"

    def test_accepts_the_slug_with_an_md_suffix(self, tmp_path):
        kb = _kb(tmp_path)
        _seed(kb, "paper", records=[_pubmed_record("111")])
        assert resolve_pmid(kb, "paper.md").pmid == "111"

    def test_nonexistent_slug_is_an_error_not_an_empty_result(self, tmp_path):
        kb = _kb(tmp_path)
        with pytest.raises(MeshSuggestError) as excinfo:
            resolve_pmid(kb, "ghost")
        assert "ghost.md" in str(excinfo.value)

    def test_source_without_a_pubmed_record_has_no_pmid(self, tmp_path):
        # An OpenAlex-only ledger: present, readable, but no PubMed provenance.
        kb = _kb(tmp_path)
        _seed(
            kb, "paper",
            records=[SourceRecord(type="openalex", id="W1", imported_at=IMPORTED_AT)],
        )
        resolution = resolve_pmid(kb, "paper")
        assert resolution.pmid is None
        assert resolution.slug == "paper"

    def test_source_with_no_ledger_at_all_has_no_pmid(self, tmp_path):
        kb = _kb(tmp_path)
        _seed(kb, "paper", records=None)  # no sidecar written
        assert resolve_pmid(kb, "paper").pmid is None

    def test_front_matter_pmid_alone_is_not_read(self, tmp_path):
        # A front-matter `pmid:` echoed by OpenAlex is a cross-reference, not PubMed
        # provenance; with no pubmed ledger record there is no PMID for this command.
        kb = _kb(tmp_path)
        md = kb / "sources" / "paper.md"
        md.write_text("---\npmid: 999\n---\n# paper\n")
        assert resolve_pmid(kb, "paper").pmid is None

    def test_empty_slug_is_rejected(self, tmp_path):
        with pytest.raises(MeshSuggestError):
            resolve_pmid(_kb(tmp_path), "   ")

    def test_corrupt_ledger_is_a_loud_error(self, tmp_path):
        kb = _kb(tmp_path)
        md = kb / "sources" / "paper.md"
        md.write_text("---\ntitle: paper\n---\n# paper\n")
        sidecar = sidecar_path(md, kb)
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text("{ not json")
        with pytest.raises(MeshSuggestError):
            resolve_pmid(kb, "paper")


# -- build_proposal: major/minor split & qualifier-only-major ---------------

class TestBuildProposal:
    def test_qualifier_only_major_counts_as_major(self):
        headings = (DESCRIPTOR_MAJOR, QUALIFIER_ONLY_MAJOR, MINOR)
        proposal = build_proposal("paper", "16354850", headings)
        assert proposal.major == (
            "Dietary Supplements",
            "Pulmonary Disease, Chronic Obstructive",
        )
        assert proposal.minor == ("Humans",)
        # The pre-2010 gap OpenAlex would misfile as minor, surfaced by name.
        assert proposal.qualifier_only_major == (
            "Pulmonary Disease, Chronic Obstructive",
        )
        assert proposal.has_mesh

    def test_no_headings_means_no_mesh(self):
        proposal = build_proposal("paper", "123", ())
        assert proposal.major == () and proposal.minor == ()
        assert proposal.qualifier_only_major == ()
        assert not proposal.has_mesh


# -- rendering: the human & porcelain surfaces state the P1 boundary --------

class TestRendering:
    def test_human_lines_lead_with_major_and_flag_the_openalex_gap(self):
        proposal = build_proposal(
            "paper", "16354850", (DESCRIPTOR_MAJOR, QUALIFIER_ONLY_MAJOR, MINOR)
        )
        text = "\n".join(proposal_lines(proposal))
        assert "PMID 16354850" in text
        assert "proposals only" in text and "nothing" in text.lower()
        # qualifier-only-major descriptor is annotated as OpenAlex's blind spot.
        assert "OpenAlex would read this as minor" in text
        # major appears before minor
        assert text.index("Major topics") < text.index("Minor topics")

    def test_human_lines_for_zero_mesh_say_so_distinctly(self):
        proposal = build_proposal("paper", "123", ())
        text = "\n".join(proposal_lines(proposal))
        assert "no MeSH" in text
        assert "not the same as having no PMID" in text

    def test_porcelain_rows_are_parseable_by_first_field(self):
        proposal = build_proposal(
            "paper", "16354850", (DESCRIPTOR_MAJOR, QUALIFIER_ONLY_MAJOR, MINOR)
        )
        rows = proposal_porcelain_lines(proposal)
        assert rows[0] == "slug\tpaper"
        assert rows[1] == "pmid\t16354850"
        # major rows carry the qualifier-only flag (0/1); minor rows do not.
        assert "major\tDietary Supplements\t0" in rows
        assert "major\tPulmonary Disease, Chronic Obstructive\t1" in rows
        assert "minor\tHumans" in rows

    def test_porcelain_zero_mesh_keeps_pmid_row_but_no_term_rows(self):
        proposal = build_proposal("paper", "123", ())
        rows = proposal_porcelain_lines(proposal)
        assert rows == ["slug\tpaper", "pmid\t123"]

    def test_no_pmid_messages_are_distinct_from_zero_mesh(self):
        human = no_pmid_line("paper")
        assert "no PubMed PMID" in human
        assert "different from a paper whose PMID simply carries no MeSH" in human
        assert no_pmid_porcelain_line("paper") == "no_pmid\tpaper"
