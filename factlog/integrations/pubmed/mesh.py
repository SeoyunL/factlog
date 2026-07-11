#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Parse a PubMed ``MeshHeadingList`` into major/minor-aware headings (#165).

Pure functions over an efetch ``Element`` — no network, no filesystem, no
optional library — in the shape of ``work_parser.py``. Kept in its own module so
this lands additively beside #164's retraction work on ``work_parser.py``.

**The #53 landmine, reproduced live (spike §7).** A MeSH descriptor is a *major
topic* of a paper iff its ``DescriptorName`` **or any of its ``QualifierName``
children** carries ``MajorTopicYN="Y"``. That disjunction is not academic: where
the majorness lives moved between eras.

* **Pre-2010** (spike's PMID 16354850, 2005): majorness rides the
  **QualifierName**. Of its headings, 1 ``DescriptorName`` is ``Y`` but 3 more
  descriptors are ``N`` while carrying a ``Y`` qualifier — true major count 4,
  descriptor-only count 1.
* **Post-2022** (spike's PMID 42277084, 2026): majorness rides the
  **DescriptorName**; every qualifier is ``N``.

OpenAlex reproduces only the descriptor-level flag, so its major-topic Jaccard
against PubMed collapses to 0.10 on 2001-2009 records. factlog ingests PubMed's
own feed precisely to keep the qualifier level — which is why this module reads
``MajorTopicYN`` on *both* levels and preserves each, not just the disjunction:
a reader must be able to see *why* a heading is major (descriptor, qualifier, or
both), not merely *that* it is.

**Coexistence with OpenAlex mesh (spec §7, source_writer.py:132-136).** OpenAlex
already contributes a flat ``mesh_terms`` list of descriptor names. PubMed's
richer reading does **not** overwrite it: :func:`mesh_provenance_fields` emits a
*source-scoped* ``pubmed_mesh_*`` namespace so both attributions survive side by
side. factlog records that two sources spoke; it does not reconcile them into one
field.
"""
from __future__ import annotations

from dataclasses import dataclass
from xml.etree import ElementTree as ET

__all__ = [
    "MeshQualifier",
    "MeshHeading",
    "parse_mesh_headings",
    "major_topic_descriptors",
    "minor_topic_descriptors",
    "mesh_provenance_fields",
]


def _is_major(element: ET.Element) -> bool:
    """True iff ``MajorTopicYN="Y"``. Absent/any-other value reads as minor.

    NLM writes ``Y``/``N`` explicitly; a missing attribute (or an unexpected
    value) is treated as *not* major rather than raising, so a sparsely-curated
    record degrades to minor instead of failing (spike §6: absence is data).
    """
    return element.get("MajorTopicYN") == "Y"


def _name(element: ET.Element) -> str | None:
    """The element's text, whitespace-collapsed, or None when empty."""
    text = element.text
    if not isinstance(text, str):
        return None
    collapsed = " ".join(text.split())
    return collapsed or None


@dataclass(frozen=True)
class MeshQualifier:
    """One ``QualifierName`` under a descriptor, with its own majorness.

    ``is_major`` mirrors this qualifier's ``MajorTopicYN`` alone — the level
    OpenAlex drops and the reason pre-2010 major counts collapse without it.
    """

    name: str
    is_major: bool
    ui: str | None = None


@dataclass(frozen=True)
class MeshHeading:
    """One ``MeshHeading``: a descriptor, its majorness, and its qualifiers.

    Both levels of ``MajorTopicYN`` are preserved, not just the derived
    disjunction, so a reader can trace *why* a heading is a major topic — the
    descriptor, a qualifier, or both. :attr:`is_major_topic` is that disjunction.
    """

    descriptor: str
    descriptor_is_major: bool
    qualifiers: tuple[MeshQualifier, ...] = ()
    descriptor_ui: str | None = None

    @property
    def is_major_topic(self) -> bool:
        """True iff the descriptor **or any** qualifier is a major topic (spike §7).

        The disjunction OpenAlex fails to compute: a descriptor flagged ``N`` is
        still a major topic when one of its qualifiers is ``Y`` (the pre-2010
        shape). Reading the descriptor alone silently undercounts major topics.
        """
        return self.descriptor_is_major or any(q.is_major for q in self.qualifiers)

    @property
    def major_by_qualifier_only(self) -> bool:
        """True iff this heading is major *only* through a qualifier.

        Exactly the case OpenAlex's descriptor-only reading loses (spike §7's
        pre-2010 record). Exposed so a test — and a reader — can name the gap.
        """
        return not self.descriptor_is_major and any(q.is_major for q in self.qualifiers)


def _find_mesh_list(element: ET.Element) -> ET.Element | None:
    """Locate the ``MeshHeadingList``, given any enclosing efetch element.

    Accepts the ``MeshHeadingList`` itself, its parent ``MedlineCitation``, or a
    whole ``PubmedArticle`` record — so a caller can pass whichever element it
    already holds. Returns ``None`` when no list is present (an unindexed record;
    spike §1 notes ``Publisher``-status records carry no MeSH at all).
    """
    if element.tag == "MeshHeadingList":
        return element
    direct = element.find("MeshHeadingList")
    if direct is not None:
        return direct
    return element.find(".//MeshHeadingList")


def _parse_qualifiers(heading: ET.Element) -> tuple[MeshQualifier, ...]:
    qualifiers = []
    for qual in heading.findall("QualifierName"):
        name = _name(qual)
        if not name:
            continue
        qualifiers.append(
            MeshQualifier(name=name, is_major=_is_major(qual), ui=qual.get("UI"))
        )
    return tuple(qualifiers)


def parse_mesh_headings(element: ET.Element | None) -> tuple[MeshHeading, ...]:
    """Parse a ``MeshHeadingList`` into structured, major/minor-aware headings.

    ``element`` may be the ``MeshHeadingList``, its ``MedlineCitation`` parent, a
    whole ``PubmedArticle`` record, or ``None``. Returns ``()`` when no list is
    present (an unindexed record is data, not an error). A heading whose
    ``DescriptorName`` has no text is skipped — nothing downstream can address a
    nameless descriptor — while every other field degrades rather than raising.
    """
    if element is None:
        return ()
    mesh_list = _find_mesh_list(element)
    if mesh_list is None:
        return ()

    headings = []
    for heading in mesh_list.findall("MeshHeading"):
        descriptor = heading.find("DescriptorName")
        if descriptor is None:
            continue
        name = _name(descriptor)
        if not name:
            continue
        headings.append(
            MeshHeading(
                descriptor=name,
                descriptor_is_major=_is_major(descriptor),
                qualifiers=_parse_qualifiers(heading),
                descriptor_ui=descriptor.get("UI"),
            )
        )
    return tuple(headings)


def major_topic_descriptors(headings: tuple[MeshHeading, ...]) -> tuple[str, ...]:
    """Descriptor names whose heading is a major topic (descriptor OR qualifier)."""
    return tuple(h.descriptor for h in headings if h.is_major_topic)


def minor_topic_descriptors(headings: tuple[MeshHeading, ...]) -> tuple[str, ...]:
    """Descriptor names whose heading is *not* a major topic."""
    return tuple(h.descriptor for h in headings if not h.is_major_topic)


def mesh_provenance_fields(headings: tuple[MeshHeading, ...]) -> dict[str, tuple[str, ...]]:
    """Source-scoped MeSH provenance, in a ``pubmed_mesh_*`` namespace.

    Returns the authoritative PubMed reading under keys that **cannot collide**
    with OpenAlex's flat ``mesh_terms`` — so both attributions coexist when the
    same paper is described by both sources (spec §7). factlog records that two
    sources spoke; it does not merge them into one field. An empty ``headings``
    yields ``{}`` so an unindexed record adds no keys.

    The actual ledger write is a downstream import issue; this is the coexistence
    *contract* the writer will honour — the distinct namespace and the
    major/minor split preserved from :func:`parse_mesh_headings`.
    """
    if not headings:
        return {}
    fields: dict[str, tuple[str, ...]] = {
        "pubmed_mesh_major": major_topic_descriptors(headings),
        "pubmed_mesh_minor": minor_topic_descriptors(headings),
    }
    return {key: value for key, value in fields.items() if value}
