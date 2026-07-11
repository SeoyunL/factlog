#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Propose canonical-alias *candidates* from a KB paper's PubMed MeSH terms (#173).

`factlog pubmed-mesh --for <SLUG>` reads the PMID a source recorded in its
provenance ledger, fetches that record's MeSH headings live, and proposes the
descriptor names as **candidate** canonical aliases — split into *major* and
*minor* topics. It never writes to the canonical vocabulary: a human gate (P1)
decides which, if any, become aliases, exactly as a fact needs review->accept.

**Why this command exists (the #53 landmine).** OpenAlex contributes a flat
``mesh_terms`` list whose descriptors are right (Jaccard 0.990) but which drops
*major-topic* status: OpenAlex reads only the ``DescriptorName``-level
``MajorTopicYN`` and throws away the ``QualifierName`` level, so on 2001-2009
records its major-topic Jaccard collapses to 0.10. An alias mined from a *minor*
MeSH term is a bad alias — the paper merely *mentioned* the concept, not what it
is *about*. So this command reads PubMed's own feed (via
:mod:`factlog.integrations.pubmed.mesh`, which preserves both levels) and shows
the **major/minor split** as the human's most useful input, not a flat list with
a flag buried in a column.

**The PMID comes from the provenance ledger, not the front matter.** A paper has
a PMID *for this purpose* when PubMed contributed one to its provenance ledger —
a ``type="pubmed"`` :class:`~...provenance.SourceRecord`, written by a
``pubmed-import`` or a PubMed merge into an existing source. An ``openalex_id``
paper that merely echoes a ``pmid:`` in its front matter has a cross-reference,
not PubMed provenance, and PubMed — not OpenAlex — is authoritative on the
major/minor split this command exists to surface. So the read boundary is the
ledger:

* a **nonexistent** slug is an *error* (nothing to read), never an empty proposal;
* a slug present but carrying **no PubMed record** in its ledger has *no PMID* —
  reported as that fact and its reason, kept categorically distinct from a paper
  whose PMID is real but simply carries **no MeSH** (an unindexed record). The
  two must never both read as "empty".

This module is pure: it resolves the PMID from the on-disk ledger and shapes the
proposal, but the live efetch (and the client injection tests use to stay
network-free) belong to the CLI handler, mirroring how ``openalex-cite`` splits
``resolve_work_id`` from the fetch.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from factlog.integrations.common.provenance import (
    ProvenanceError,
    read_provenance,
    sidecar_path,
)
from factlog.integrations.pubmed.mesh import (
    MeshHeading,
    major_topic_descriptors,
    minor_topic_descriptors,
)

__all__ = [
    "MeshSuggestError",
    "PmidResolution",
    "MeshProposal",
    "resolve_pmid",
    "build_proposal",
    "proposal_lines",
    "proposal_porcelain_lines",
    "no_pmid_line",
    "no_pmid_porcelain_line",
]

#: The provenance record type a ``pubmed-import`` / PubMed merge writes; its ``id``
#: is the PMID. Kept as a name so the one place that knows "PubMed's ledger record
#: is typed 'pubmed'" is this constant, not a bare string in a comprehension.
_PUBMED_RECORD_TYPE = "pubmed"


class MeshSuggestError(Exception):
    """A ``pubmed-mesh`` request cannot be satisfied (bad/absent slug, bad ledger).

    Its own class so the CLI reports a *user* error (a nonexistent slug, an
    unreadable ledger) distinctly from a network failure the client raises, and
    from the two non-error outcomes — no PMID, or no MeSH — which are *values*,
    never exceptions.
    """


@dataclass(frozen=True)
class PmidResolution:
    """The result of resolving ``--for <SLUG>`` against the provenance ledger.

    ``pmid`` is the PMID PubMed recorded for the paper, or ``None`` when the paper
    exists but its ledger carries no PubMed record. ``None`` is a *value* (report
    "no PMID, and why"), never confused with a nonexistent slug — which raises.
    """

    slug: str
    pmid: str | None


@dataclass(frozen=True)
class MeshProposal:
    """MeSH descriptors proposed as candidate aliases, split major vs minor.

    Both splits are descriptor names in the record's order. ``qualifier_only_major``
    is the subset of ``major`` whose heading is a major topic **only** through a
    ``QualifierName`` — exactly the descriptors OpenAlex's descriptor-only reading
    would misfile as minor (the #53 gap), surfaced so the CLI and a human can see
    where PubMed and OpenAlex disagree. Empty ``major`` *and* empty ``minor`` means
    the record carries no MeSH at all (unindexed) — a real, distinct outcome from a
    paper that has no PMID.
    """

    slug: str
    pmid: str
    major: tuple[str, ...]
    minor: tuple[str, ...]
    qualifier_only_major: tuple[str, ...]

    @property
    def has_mesh(self) -> bool:
        return bool(self.major or self.minor)


def _normalize_slug(slug: object) -> str:
    """The ``sources/`` filename for a slug, with or without a ``.md`` suffix."""
    if not isinstance(slug, str) or not slug.strip():
        raise MeshSuggestError("--for needs a non-empty source slug.")
    name = slug.strip()
    if not name.endswith(".md"):
        name += ".md"
    return name


def resolve_pmid(kb_root: Path | str, slug: str) -> PmidResolution:
    """Resolve ``--for <SLUG>`` to the PMID recorded in its provenance ledger.

    Raises :class:`MeshSuggestError` when no ``sources/<slug>.md`` exists — a
    nonexistent slug is a user error with nothing to propose, never an empty
    result — or when the ledger is present but unreadable (a corrupt sidecar is a
    loud failure, not a silent "no PMID").

    Returns a :class:`PmidResolution` whose ``pmid`` is ``None`` when the source
    exists but its ledger holds no ``type="pubmed"`` record: the paper simply has
    no PMID for PubMed to be asked about. That ``None`` is a value the CLI reports
    with its reason, kept distinct from an unindexed (zero-MeSH) record.
    """
    name = _normalize_slug(slug)
    root = Path(kb_root)
    source_path = root / "sources" / name
    if not source_path.is_file():
        raise MeshSuggestError(f"no source {name} in {root / 'sources'}")

    sidecar = sidecar_path(source_path, root)
    try:
        provenance = read_provenance(sidecar)
    except ProvenanceError as exc:
        raise MeshSuggestError(
            f"{name} has an unreadable provenance ledger: {exc}"
        ) from exc

    for record in provenance.records:
        if record.type == _PUBMED_RECORD_TYPE and record.id:
            return PmidResolution(slug=name[: -len(".md")], pmid=record.id)
    return PmidResolution(slug=name[: -len(".md")], pmid=None)


def build_proposal(
    slug: str, pmid: str, headings: tuple[MeshHeading, ...]
) -> MeshProposal:
    """Shape parsed MeSH headings into a major/minor candidate proposal.

    Preserves the split :mod:`factlog.integrations.pubmed.mesh` computes — a
    heading is major iff its descriptor **or any** qualifier is a major topic —
    and pulls out the qualifier-only-major descriptors so the reader can see the
    ones OpenAlex would drop. Pure: no network, no clock, no write.
    """
    major = major_topic_descriptors(headings)
    minor = minor_topic_descriptors(headings)
    qualifier_only_major = tuple(
        h.descriptor for h in headings if h.major_by_qualifier_only
    )
    return MeshProposal(
        slug=slug,
        pmid=pmid,
        major=major,
        minor=minor,
        qualifier_only_major=qualifier_only_major,
    )


# -- rendering ---------------------------------------------------------------
#
# Two surfaces, both stating the same P1 boundary in words: these are *candidates*
# and nothing is written. The human surface leads with the major topics (the
# useful aliases) and marks each qualifier-only-major descriptor as the place
# OpenAlex would disagree; the porcelain surface is a stable tab-separated
# contract a script can parse by first field.

_QUALIFIER_ONLY_NOTE = "major via qualifier only — OpenAlex would read this as minor"


def proposal_lines(proposal: MeshProposal) -> list[str]:
    """Human-readable proposal, major topics first, candidates only."""
    lines = [
        f"factlog pubmed-mesh: {proposal.slug} (PMID {proposal.pmid})",
        "",
    ]
    if not proposal.has_mesh:
        lines.append(
            f"PMID {proposal.pmid} carries no MeSH terms (an unindexed record); "
            "there is nothing to propose. This is not the same as having no PMID."
        )
        return lines

    lines.append(
        "Candidate canonical aliases from PubMed MeSH — proposals only, nothing "
        "written. A human decides which, if any, become canonical aliases."
    )
    lines.append("")
    qualifier_only = set(proposal.qualifier_only_major)
    lines.append("  Major topics (what the paper is about — the useful aliases):")
    if proposal.major:
        for descriptor in proposal.major:
            note = f"  [{_QUALIFIER_ONLY_NOTE}]" if descriptor in qualifier_only else ""
            lines.append(f"    - {descriptor}{note}")
    else:
        lines.append("    (none)")
    lines.append("  Minor topics (merely mentioned — usually a weak alias):")
    if proposal.minor:
        for descriptor in proposal.minor:
            lines.append(f"    - {descriptor}")
    else:
        lines.append("    (none)")
    lines.append("")
    lines.append("Nothing was written. These are candidates for human review.")
    return lines


def proposal_porcelain_lines(proposal: MeshProposal) -> list[str]:
    """Machine-readable proposal: tab-separated rows, parseable by first field.

    Rows::

        slug\t<slug>
        pmid\t<pmid>
        major\t<descriptor>\t<qualifier_only 0|1>
        minor\t<descriptor>

    A record with no MeSH emits only the ``slug``/``pmid`` rows — distinguishable
    from a no-PMID paper (:func:`no_pmid_porcelain_line`) which emits neither a
    ``pmid`` row nor any ``major``/``minor`` row.
    """
    from factlog.integrations.common.porcelain import porcelain_field

    rows = [
        f"slug\t{porcelain_field(proposal.slug)}",
        f"pmid\t{porcelain_field(proposal.pmid)}",
    ]
    qualifier_only = set(proposal.qualifier_only_major)
    for descriptor in proposal.major:
        flag = "1" if descriptor in qualifier_only else "0"
        rows.append(f"major\t{porcelain_field(descriptor)}\t{flag}")
    for descriptor in proposal.minor:
        rows.append(f"minor\t{porcelain_field(descriptor)}")
    return rows


def no_pmid_line(slug: str) -> str:
    """The human message for a paper whose ledger records no PMID.

    States the fact *and its reason*, and never reads as "no MeSH": a paper with
    no PMID is one PubMed was never asked about, distinct from an unindexed record
    that has a PMID but no MeSH.
    """
    return (
        f"factlog pubmed-mesh: {slug} records no PubMed PMID in its provenance "
        "ledger, so there is nothing to propose. Import it with 'factlog "
        "pubmed-import', or merge a PubMed record into it, to give it a PMID. "
        "(This is different from a paper whose PMID simply carries no MeSH terms.)"
    )


def no_pmid_porcelain_line(slug: str) -> str:
    """The porcelain row for a no-PMID paper: ``no_pmid\t<slug>``.

    A distinct first field so a script never confuses it with a zero-MeSH record,
    which still emits ``slug``/``pmid`` rows.
    """
    from factlog.integrations.common.porcelain import porcelain_field

    return f"no_pmid\t{porcelain_field(slug)}"
