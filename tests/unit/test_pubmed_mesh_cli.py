# SPDX-License-Identifier: Apache-2.0
"""CLI tests for ``factlog pubmed-mesh --for <SLUG>`` (#173).

The real PubMed client is replaced via ``_make_pubmed_client`` so the command
runs without the network. A temp KB seeds a source ``.md`` plus its provenance
ledger (where the PMID is read from). The focus is the issue's Done-when: a
major/minor split, a pre-2010 qualifier-only major appearing as major (where
OpenAlex would be wrong), the PMID-absent vs zero-MeSH distinction, the
candidate-only boundary (nothing written), and a nonexistent slug as an error.
"""
from __future__ import annotations

import pytest

from factlog import cli
from factlog.integrations.common.provenance import (
    Provenance,
    SourceRecord,
    sidecar_path,
    write_provenance,
)

IMPORTED_AT = "2026-01-01T00:00:00+00:00"


def _kb(tmp_path):
    (tmp_path / "sources").mkdir()
    # A KB-scoped contact email so `_pubmed_prepare` is satisfied regardless of
    # which folded variant of the helper wins at the pre-merge rebase.
    (tmp_path / "policy").mkdir()
    (tmp_path / "policy" / "pubmed-config.toml").write_text(
        '[client]\nemail = "dev@example.org"\n'
    )
    return tmp_path


def _seed(kb, name, *, pmid=None, extra_records=()):
    """Write a source .md and its ledger; optionally a PubMed record with `pmid`."""
    md = kb / "sources" / f"{name}.md"
    md.write_text(f"---\ntitle: {name}\n---\n# {name}\n")
    records = list(extra_records)
    if pmid is not None:
        records.append(
            SourceRecord(type="pubmed", id=pmid, imported_at=IMPORTED_AT, fields={})
        )
    if records:
        write_provenance(sidecar_path(md, kb), Provenance(records=records))
    return name


# -- efetch XML fixtures -----------------------------------------------------

# Pre-2010 shape (spike §7, PMID 16354850): majorness rides the QualifierName. One
# descriptor is Y; another is N but carries a Y qualifier (a MAJOR topic OpenAlex
# would drop); a third is a plain minor.
PRE_2010_EFETCH = """<PubmedArticleSet><PubmedArticle><MedlineCitation>
<PMID Version="1">16354850</PMID>
<Article><ArticleTitle>Omega-3 fatty acids in COPD.</ArticleTitle></Article>
<MeshHeadingList>
  <MeshHeading>
    <DescriptorName UI="D019587" MajorTopicYN="Y">Dietary Supplements</DescriptorName>
  </MeshHeading>
  <MeshHeading>
    <DescriptorName UI="D029424" MajorTopicYN="N">Pulmonary Disease, Chronic Obstructive</DescriptorName>
    <QualifierName UI="Q000188" MajorTopicYN="Y">drug therapy</QualifierName>
  </MeshHeading>
  <MeshHeading>
    <DescriptorName UI="D006801" MajorTopicYN="N">Humans</DescriptorName>
  </MeshHeading>
</MeshHeadingList>
</MedlineCitation></PubmedArticle></PubmedArticleSet>"""

# A record with no MeSH at all (unindexed): has a PMID, but nothing to propose.
ZERO_MESH_EFETCH = """<PubmedArticleSet><PubmedArticle><MedlineCitation>
<PMID Version="1">55555555</PMID>
<Article><ArticleTitle>A brand-new, not-yet-indexed paper.</ArticleTitle></Article>
</MedlineCitation></PubmedArticle></PubmedArticleSet>"""

# An empty set: the requested PMID returned nothing (deleted).
EMPTY_EFETCH = "<PubmedArticleSet/>"


class FakePubMedClient:
    """Replays a canned efetch body and records the ids it was asked for."""

    def __init__(self, efetch_body):
        self._efetch = efetch_body
        self.calls = []

    def efetch(self, ids):
        self.calls.append(("efetch", tuple(ids)))
        return self._efetch


@pytest.fixture
def fake(monkeypatch):
    def install(client):
        monkeypatch.setattr(cli, "_make_pubmed_client", lambda config: client)
        return client
    return install


def run(argv):
    args = cli.build_parser().parse_args(argv)
    return args.func(args)


# -- the major/minor split, and the pre-2010 qualifier-only major -----------

class TestMajorMinorSplit:
    def test_major_and_minor_are_visually_distinct(self, tmp_path, fake, capsys):
        kb = _kb(tmp_path)
        _seed(kb, "copd", pmid="16354850")
        client = fake(FakePubMedClient(PRE_2010_EFETCH))
        rc = run(["pubmed-mesh", "--for", "copd", "--target", str(kb)])
        assert rc == 0
        out = capsys.readouterr().out
        assert client.calls == [("efetch", ("16354850",))]
        # Split headings, major before minor.
        assert "Major topics" in out and "Minor topics" in out
        assert out.index("Major topics") < out.index("Minor topics")
        # Dietary Supplements (descriptor-major) and the qualifier-only major both
        # land under major; Humans is minor.
        assert "Dietary Supplements" in out
        assert "Pulmonary Disease, Chronic Obstructive" in out
        assert "Humans" in out

    def test_pre_2010_qualifier_only_major_appears_as_major(self, tmp_path, fake, capsys):
        # The exact case OpenAlex gets wrong: a descriptor flagged N whose qualifier
        # is Y is a MAJOR topic. It must be flagged as OpenAlex's blind spot.
        kb = _kb(tmp_path)
        _seed(kb, "copd", pmid="16354850")
        fake(FakePubMedClient(PRE_2010_EFETCH))
        rc = run(["pubmed-mesh", "--for", "copd", "--porcelain", "--target", str(kb)])
        assert rc == 0
        rows = capsys.readouterr().out.splitlines()
        assert "major\tDietary Supplements\t0" in rows
        # qualifier-only-major flag = 1
        assert "major\tPulmonary Disease, Chronic Obstructive\t1" in rows
        assert "minor\tHumans" in rows

    def test_nothing_is_written_to_the_canonical_vocabulary(self, tmp_path, fake, capsys):
        kb = _kb(tmp_path)
        _seed(kb, "copd", pmid="16354850")
        fake(FakePubMedClient(PRE_2010_EFETCH))
        rc = run(["pubmed-mesh", "--for", "copd", "--target", str(kb)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "candidates for human review" in out
        # Candidate boundary (P1): the command creates no vocabulary/canonical files.
        assert not (kb / "vocabulary").exists()
        assert not (kb / "canonical").exists()
        # Only the seeded source + its ledger exist under the KB.
        assert sorted(p.name for p in (kb / "sources").iterdir()) == ["copd.md"]


# -- PMID-absent vs zero-MeSH (must not both read as "empty") ---------------

class TestPmidAbsentVsZeroMesh:
    def test_no_pmid_is_reported_with_its_reason_without_a_fetch(self, tmp_path, monkeypatch, capsys):
        # An OpenAlex-only source: exists, but no PubMed provenance -> no PMID. The
        # client must never be built (nothing to fetch).
        kb = _kb(tmp_path)
        _seed(
            kb, "oa-only",
            extra_records=[SourceRecord(type="openalex", id="W1", imported_at=IMPORTED_AT)],
        )
        monkeypatch.setattr(
            cli, "_make_pubmed_client",
            lambda config: (_ for _ in ()).throw(AssertionError("built a client")),
        )
        rc = run(["pubmed-mesh", "--for", "oa-only", "--target", str(kb)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "records no PubMed PMID" in out
        assert "no MeSH" in out  # names the distinction explicitly

    def test_zero_mesh_record_is_reported_as_unindexed_not_no_pmid(self, tmp_path, fake, capsys):
        kb = _kb(tmp_path)
        _seed(kb, "fresh", pmid="55555555")
        fake(FakePubMedClient(ZERO_MESH_EFETCH))
        rc = run(["pubmed-mesh", "--for", "fresh", "--target", str(kb)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "PMID 55555555" in out
        assert "no MeSH" in out and "unindexed" in out
        assert "records no PubMed PMID" not in out  # NOT the no-PMID message

    def test_porcelain_distinguishes_no_pmid_from_zero_mesh(self, tmp_path, fake, monkeypatch, capsys):
        kb = _kb(tmp_path)
        _seed(kb, "fresh", pmid="55555555")
        _seed(
            kb, "oa-only",
            extra_records=[SourceRecord(type="openalex", id="W1", imported_at=IMPORTED_AT)],
        )
        # zero-MeSH: slug + pmid rows, no term rows.
        fake(FakePubMedClient(ZERO_MESH_EFETCH))
        run(["pubmed-mesh", "--for", "fresh", "--porcelain", "--target", str(kb)])
        zero = capsys.readouterr().out.splitlines()
        assert zero == ["slug\tfresh", "pmid\t55555555"]
        # no-PMID: a distinct first field, no pmid row.
        monkeypatch.setattr(
            cli, "_make_pubmed_client",
            lambda config: (_ for _ in ()).throw(AssertionError("built")),
        )
        run(["pubmed-mesh", "--for", "oa-only", "--porcelain", "--target", str(kb)])
        nopmid = capsys.readouterr().out.splitlines()
        assert nopmid == ["no_pmid\toa-only"]


# -- errors: nonexistent slug, and an upstream-gone PMID --------------------

class TestErrors:
    def test_nonexistent_slug_is_an_error(self, tmp_path, monkeypatch, capsys):
        kb = _kb(tmp_path)
        monkeypatch.setattr(
            cli, "_make_pubmed_client",
            lambda config: (_ for _ in ()).throw(AssertionError("built")),
        )
        rc = run(["pubmed-mesh", "--for", "ghost", "--target", str(kb)])
        assert rc == 1
        assert "ghost.md" in capsys.readouterr().err

    def test_deleted_pmid_is_a_reported_signal_not_zero_mesh(self, tmp_path, fake, capsys):
        kb = _kb(tmp_path)
        _seed(kb, "gone", pmid="16354850")
        fake(FakePubMedClient(EMPTY_EFETCH))
        rc = run(["pubmed-mesh", "--for", "gone", "--target", str(kb)])
        assert rc == 1
        err = capsys.readouterr().err
        assert "16354850" in err and "no record" in err
