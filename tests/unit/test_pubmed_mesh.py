# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the PubMed MeSH major/minor parser (#165, spec §7, spike §7).

The fixtures are inline efetch XML shaped like the #160 spike's *recorded*
MeshHeadingList responses (`docs/pubmed-spike-findings.md` §7): the pre-2010
record (PMID 16354850) where majorness rides the ``QualifierName`` — the exact
information OpenAlex drops — and the post-2022 record (PMID 42277084) where it
rides the ``DescriptorName``. The reason these two eras exist as separate
fixtures is the #53 landmine: a descriptor-only reading undercounts pre-2010
major topics (1 vs the true 4) and collapses major-topic Jaccard to 0.10.
"""
from __future__ import annotations

from xml.etree import ElementTree as ET

from factlog.integrations.openalex.work_parser import ParsedWork
from factlog.integrations.pubmed.mesh import (
    MeshHeading,
    MeshQualifier,
    major_topic_descriptors,
    mesh_provenance_fields,
    minor_topic_descriptors,
    parse_mesh_headings,
)
from factlog.integrations.pubmed.work_parser import (
    ParsedPubMedWork,
    parse_efetch_response,
)

# Pre-2010 record, spike §7's PMID 16354850 (2005). Majorness rides the
# QualifierName: only 1 DescriptorName is Y (Dietary Supplements); three more
# descriptors are N but each carries a Y qualifier. Descriptor-only reading -> 1
# major; the truth including qualifier majorness -> 4. This is #53's mechanism.
PRE_2010_MESH_XML = """<?xml version="1.0" ?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID Version="1">16354850</PMID>
      <Article>
        <ArticleTitle>Omega-3 fatty acids in COPD.</ArticleTitle>
      </Article>
      <MeshHeadingList>
        <MeshHeading>
          <DescriptorName UI="D019587" MajorTopicYN="Y">Dietary Supplements</DescriptorName>
        </MeshHeading>
        <MeshHeading>
          <DescriptorName UI="D015525" MajorTopicYN="N">Fatty Acids, Omega-3</DescriptorName>
          <QualifierName UI="Q000627" MajorTopicYN="Y">therapeutic use</QualifierName>
          <QualifierName UI="Q000008" MajorTopicYN="N">administration &amp; dosage</QualifierName>
        </MeshHeading>
        <MeshHeading>
          <DescriptorName UI="D018836" MajorTopicYN="N">Inflammation Mediators</DescriptorName>
          <QualifierName UI="Q000032" MajorTopicYN="Y">analysis</QualifierName>
        </MeshHeading>
        <MeshHeading>
          <DescriptorName UI="D029424" MajorTopicYN="N">Pulmonary Disease, Chronic Obstructive</DescriptorName>
          <QualifierName UI="Q000188" MajorTopicYN="Y">drug therapy</QualifierName>
        </MeshHeading>
        <MeshHeading>
          <DescriptorName UI="D006801" MajorTopicYN="N">Humans</DescriptorName>
        </MeshHeading>
      </MeshHeadingList>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""

# Post-2022 record, spike §7's PMID 42277084 (2026). Majorness rides the
# DescriptorName: 3 descriptors Y, every qualifier N. Descriptor-only reading is
# sufficient here (this is the 0.98-Jaccard era) -> a correct parser agrees.
POST_2022_MESH_XML = """<?xml version="1.0" ?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID Version="1">42277084</PMID>
      <Article>
        <ArticleTitle>Immobilized oxidoreductases for biofuel cells.</ArticleTitle>
      </Article>
      <MeshHeadingList>
        <MeshHeading>
          <DescriptorName UI="D000068323" MajorTopicYN="Y">Bioelectric Energy Sources</DescriptorName>
        </MeshHeading>
        <MeshHeading>
          <DescriptorName UI="D010088" MajorTopicYN="Y">Oxidoreductases</DescriptorName>
          <QualifierName UI="Q000378" MajorTopicYN="N">metabolism</QualifierName>
        </MeshHeading>
        <MeshHeading>
          <DescriptorName UI="D004798" MajorTopicYN="Y">Enzymes, Immobilized</DescriptorName>
          <QualifierName UI="Q000378" MajorTopicYN="N">metabolism</QualifierName>
        </MeshHeading>
        <MeshHeading>
          <DescriptorName UI="D000818" MajorTopicYN="N">Animals</DescriptorName>
        </MeshHeading>
      </MeshHeadingList>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""

# An unindexed record (spike §1: Publisher-status records carry no MeSH).
NO_MESH_XML = """<?xml version="1.0" ?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID Version="1">33301246</PMID>
      <Article><ArticleTitle>A trial with no MeSH indexing.</ArticleTitle></Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""


def _headings(xml_text: str) -> tuple[MeshHeading, ...]:
    """The mesh_headings the full parser lands for a one-record efetch body."""
    outcome = parse_efetch_response(xml_text, [_root_pmid(xml_text)])
    return outcome.works[0].mesh_headings


def _root_pmid(xml_text: str) -> str:
    return ET.fromstring(xml_text).find(".//PMID").text


# ---------------------------------------------------------------------------
# Pre-2010: qualifier-level majorness — the point OpenAlex fails, factlog does not
# ---------------------------------------------------------------------------

def test_pre_2010_reads_qualifier_level_majorness():
    """The pre-2010 record's true major count is 4, not the descriptor-only 1.

    This is the direct reproduction of #53's 0.10 collapse: a descriptor-only
    reading (what OpenAlex keeps) finds 1 major topic; reading QualifierName too
    finds 4. The assertion pins that factlog reads the qualifier level.
    """
    headings = _headings(PRE_2010_MESH_XML)

    descriptor_only_major = [h for h in headings if h.descriptor_is_major]
    assert len(descriptor_only_major) == 1  # what OpenAlex would report
    assert descriptor_only_major[0].descriptor == "Dietary Supplements"

    true_major = major_topic_descriptors(headings)
    assert set(true_major) == {
        "Dietary Supplements",
        "Fatty Acids, Omega-3",
        "Inflammation Mediators",
        "Pulmonary Disease, Chronic Obstructive",
    }
    assert len(true_major) == 4


def test_pre_2010_qualifier_only_descriptor_reported_major():
    """A descriptor flagged N is a major topic when a qualifier is Y (disjunction)."""
    headings = {h.descriptor: h for h in _headings(PRE_2010_MESH_XML)}

    omega3 = headings["Fatty Acids, Omega-3"]
    assert omega3.descriptor_is_major is False  # descriptor says minor...
    assert omega3.is_major_topic is True  # ...but a qualifier makes it major
    assert omega3.major_by_qualifier_only is True

    # And the qualifier majorness is preserved individually, not just OR-ed away:
    quals = {q.name: q for q in omega3.qualifiers}
    assert quals["therapeutic use"].is_major is True
    assert quals["administration & dosage"].is_major is False


def test_pre_2010_minor_headings_stay_minor():
    """Humans (descriptor N, no Y qualifier) is not promoted to major."""
    headings = _headings(PRE_2010_MESH_XML)
    minor = minor_topic_descriptors(headings)
    assert "Humans" in minor
    humans = next(h for h in headings if h.descriptor == "Humans")
    assert humans.is_major_topic is False
    assert humans.major_by_qualifier_only is False


# ---------------------------------------------------------------------------
# Post-2022: descriptor-level majorness — the era descriptor-only suffices
# ---------------------------------------------------------------------------

def test_post_2022_reads_descriptor_level_majorness():
    """Post-2022 major topics ride the DescriptorName; qualifiers are all minor."""
    headings = _headings(POST_2022_MESH_XML)

    true_major = major_topic_descriptors(headings)
    assert set(true_major) == {
        "Bioelectric Energy Sources",
        "Oxidoreductases",
        "Enzymes, Immobilized",
    }
    # No heading here is major *only* by a qualifier — descriptor-only would agree.
    assert not any(h.major_by_qualifier_only for h in headings)
    for heading in headings:
        assert all(q.is_major is False for q in heading.qualifiers)


# ---------------------------------------------------------------------------
# Absence and structure
# ---------------------------------------------------------------------------

def test_no_mesh_heading_list_is_empty_not_error():
    headings = _headings(NO_MESH_XML)
    assert headings == ()
    assert major_topic_descriptors(headings) == ()
    assert mesh_provenance_fields(headings) == {}


def test_parse_accepts_meshheadinglist_medlinecitation_or_record():
    """The pure function takes whichever enclosing element a caller holds."""
    root = ET.fromstring(PRE_2010_MESH_XML)
    record = root.find("PubmedArticle")
    citation = record.find("MedlineCitation")
    mesh_list = citation.find("MeshHeadingList")

    from_record = parse_mesh_headings(record)
    from_citation = parse_mesh_headings(citation)
    from_list = parse_mesh_headings(mesh_list)

    assert from_record == from_citation == from_list
    assert len(from_record) == 5


def test_parse_none_is_empty():
    assert parse_mesh_headings(None) == ()


def test_heading_preserves_descriptor_ui_and_qualifier_ui():
    """Provenance UIs survive so a downstream reader can resolve the descriptor."""
    headings = {h.descriptor: h for h in _headings(PRE_2010_MESH_XML)}
    omega3 = headings["Fatty Acids, Omega-3"]
    assert omega3.descriptor_ui == "D015525"
    assert omega3.qualifiers[0].ui == "Q000627"


# ---------------------------------------------------------------------------
# Coexistence with OpenAlex mesh_terms (spec §7): both attributions survive
# ---------------------------------------------------------------------------

def test_pubmed_mesh_provenance_is_source_scoped():
    """The provenance namespace cannot collide with OpenAlex's ``mesh_terms``."""
    headings = _headings(PRE_2010_MESH_XML)
    fields = mesh_provenance_fields(headings)

    assert set(fields) == {"pubmed_mesh_major", "pubmed_mesh_minor"}
    assert "mesh_terms" not in fields  # never overwrites the OpenAlex key
    # The major/minor split is preserved through serialization, not flattened:
    assert set(fields["pubmed_mesh_major"]) == {
        "Dietary Supplements",
        "Fatty Acids, Omega-3",
        "Inflammation Mediators",
        "Pulmonary Disease, Chronic Obstructive",
    }
    assert "Humans" in fields["pubmed_mesh_minor"]


def test_openalex_mesh_terms_and_pubmed_mesh_coexist():
    """A record already carrying OpenAlex ``mesh_terms`` keeps them AND gains PubMed mesh.

    Design-level: the two sources use distinct keys, so merging their front-matter
    contributions loses neither. factlog records that two sources spoke; it does
    not reconcile them into one field (spec §7). The actual ledger write is a
    downstream import issue — this pins the coexistence contract.
    """
    # OpenAlex's flat descriptor list for the same paper (no majorness).
    openalex = ParsedWork(
        openalex_id="W1",
        title="Omega-3 fatty acids in COPD.",
        mesh_terms=("Dietary Supplements", "Fatty Acids, Omega-3", "Humans"),
    )
    # PubMed's richer reading of the same paper.
    pubmed = ParsedPubMedWork(pmid="16354850", mesh_headings=_headings(PRE_2010_MESH_XML))

    front_matter: dict[str, object] = {}
    if openalex.mesh_terms:
        front_matter["mesh_terms"] = openalex.mesh_terms
    front_matter.update(mesh_provenance_fields(pubmed.mesh_headings))

    # OpenAlex's flat list is untouched...
    assert front_matter["mesh_terms"] == ("Dietary Supplements", "Fatty Acids, Omega-3", "Humans")
    # ...and PubMed's major/minor reading is present alongside it.
    assert "Fatty Acids, Omega-3" in front_matter["pubmed_mesh_major"]
    assert front_matter["mesh_terms"] != front_matter["pubmed_mesh_major"]


def test_manual_construction_matches_parsed_shape():
    """The dataclass shape is what a hand-built heading produces (schema guard)."""
    manual = MeshHeading(
        descriptor="Fatty Acids, Omega-3",
        descriptor_is_major=False,
        qualifiers=(MeshQualifier(name="therapeutic use", is_major=True, ui="Q000627"),
                    MeshQualifier(name="administration & dosage", is_major=False, ui="Q000008")),
        descriptor_ui="D015525",
    )
    assert manual.is_major_topic is True
    assert manual.major_by_qualifier_only is True
