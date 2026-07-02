# SPDX-License-Identifier: Apache-2.0
"""Unit tests for #227 SLICE 1: canonical relation name acceptance in the query
validator (classify_query) and schema_context canonical section.

These tests are engine-free and read-only — no accepted.dl, no pyrewire.
"""
from __future__ import annotations

import factlog.common as fcommon
import ask_router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_alias_file(tmp_path, text: str):
    """Write text to policy/relation-aliases.md under tmp_path."""
    policy = tmp_path / "policy"
    policy.mkdir(parents=True, exist_ok=True)
    (policy / "relation-aliases.md").write_text(text, encoding="utf-8")
    return tmp_path


def _make_facts(rows: list[tuple[str, str, str]]) -> list[dict[str, str]]:
    """Build a minimal accepted-facts list (status=confirmed) from (s, r, o) tuples."""
    return [
        {"subject": s, "relation": r, "object": o, "status": "confirmed",
         "source": "sources/test.md", "confidence": "0.90", "note": ""}
        for s, r, o in rows
    ]


# ---------------------------------------------------------------------------
# classify_query: canonical relation name acceptance
# ---------------------------------------------------------------------------

class TestCanonicalRelationAcceptance:
    """A relation name that is a declared canonical should be engine-routable."""

    def test_canonical_name_validates_ok(self, tmp_path, monkeypatch):
        """relation(S, "published_year", O)? with alias file -> QUERY_OK."""
        _write_alias_file(tmp_path, (
            "- `게재연도` -> `published_year`\n"
            "- `publication_year` -> `published_year`\n"
        ))
        # Facts use the surface variants, not the canonical.
        facts = _make_facts([
            ("논문A", "게재연도", "2005"),
            ("논문B", "publication_year", "2007"),
        ])
        # Patch the real module (factlog.common) — tools/common.py is a shim.
        monkeypatch.setattr(fcommon, "POLICY_DIR", tmp_path / "policy")
        ok, code, reason = fcommon.classify_query(
            'relation(S, "published_year", O)?', facts, policy_program=""
        )
        assert ok is True, f"expected ok=True, got code={code!r} reason={reason!r}"
        assert code == fcommon.QUERY_OK

    def test_canonical_name_with_specific_subject_validates_ok(self, tmp_path, monkeypatch):
        """relation("논문A", "published_year", X)? -> QUERY_OK (fact exists via variant)."""
        _write_alias_file(tmp_path, "- `게재연도` -> `published_year`\n")
        facts = _make_facts([("논문A", "게재연도", "2005")])
        monkeypatch.setattr(fcommon, "POLICY_DIR", tmp_path / "policy")
        ok, code, reason = fcommon.classify_query(
            'relation("논문A", "published_year", X)?', facts, policy_program=""
        )
        assert ok is True, f"code={code!r} reason={reason!r}"
        assert code == fcommon.QUERY_OK

    def test_genuinely_unknown_relation_still_rejected(self, tmp_path, monkeypatch):
        """A relation that is neither in accepted facts nor a canonical -> RELATION_NOT_ACCEPTED."""
        _write_alias_file(tmp_path, "- `게재연도` -> `published_year`\n")
        facts = _make_facts([("논문A", "게재연도", "2005")])
        monkeypatch.setattr(fcommon, "POLICY_DIR", tmp_path / "policy")
        ok, code, reason = fcommon.classify_query(
            'relation("논문A", "completely_unknown", X)?', facts, policy_program=""
        )
        assert ok is False
        assert code == fcommon.QUERY_RELATION_NOT_ACCEPTED

    def test_no_alias_file_canonical_unknown_still_rejected(self, tmp_path, monkeypatch):
        """Without an alias file, a name not in accepted facts is still rejected."""
        (tmp_path / "policy").mkdir(parents=True, exist_ok=True)
        facts = _make_facts([("논문A", "게재연도", "2005")])
        monkeypatch.setattr(fcommon, "POLICY_DIR", tmp_path / "policy")
        ok, code, reason = fcommon.classify_query(
            'relation("논문A", "published_year", X)?', facts, policy_program=""
        )
        assert ok is False
        assert code == fcommon.QUERY_RELATION_NOT_ACCEPTED

    def test_fact_absent_when_no_surface_variant_rows_match(self, tmp_path, monkeypatch):
        """Canonical accepted but NO matching surface-variant rows -> QUERY_FACT_ABSENT."""
        _write_alias_file(tmp_path, "- `게재연도` -> `published_year`\n")
        # No facts with 게재연도 for this subject — only unrelated relation.
        facts = _make_facts([("논문A", "저자", "김철수")])
        monkeypatch.setattr(fcommon, "POLICY_DIR", tmp_path / "policy")
        ok, code, reason = fcommon.classify_query(
            'relation("논문A", "published_year", X)?', facts, policy_program=""
        )
        # QUERY_FACT_ABSENT routes to engine (verified negative) — not wiki.
        assert ok is False
        assert code == fcommon.QUERY_FACT_ABSENT

    def test_behavior_without_alias_file_byte_identical(self, tmp_path, monkeypatch):
        """No alias file -> classify_query behavior unchanged (opt-in no-op)."""
        (tmp_path / "policy").mkdir(parents=True, exist_ok=True)
        facts = _make_facts([("Acme", "uses", "FastAPI")])
        monkeypatch.setattr(fcommon, "POLICY_DIR", tmp_path / "policy")
        # Existing relation -> ok
        ok, code, _ = fcommon.classify_query(
            'relation("Acme", "uses", V)?', facts, policy_program=""
        )
        assert ok is True and code == fcommon.QUERY_OK
        # Unknown relation -> not_accepted
        ok2, code2, _ = fcommon.classify_query(
            'relation("Acme", "published_year", V)?', facts, policy_program=""
        )
        assert ok2 is False and code2 == fcommon.QUERY_RELATION_NOT_ACCEPTED


# ---------------------------------------------------------------------------
# schema_context: canonical section
# ---------------------------------------------------------------------------

class TestSchemaContextCanonicalSection:
    """schema_context() includes a canonical section iff an alias file exists."""

    def _make_kb(self, tmp_path, alias_text: str | None):
        """Set up a minimal KB under tmp_path with optional alias file."""
        for d in ("facts", "policy", "sources", "pages", "decisions"):
            (tmp_path / d).mkdir(parents=True, exist_ok=True)
        # Minimal accepted.dl
        (tmp_path / "facts" / "accepted.dl").write_text(
            'relation("논문A", "게재연도", "2005").\n'
            'relation("논문B", "publication_year", "2007").\n',
            encoding="utf-8",
        )
        # Minimal candidates.csv
        (tmp_path / "facts" / "candidates.csv").write_text(
            "subject,relation,object,source,status,confidence,note\n"
            "논문A,게재연도,2005,sources/test.md,confirmed,0.90,\n"
            "논문B,publication_year,2007,sources/test.md,confirmed,0.90,\n",
            encoding="utf-8",
        )
        if alias_text is not None:
            (tmp_path / "policy" / "relation-aliases.md").write_text(
                alias_text, encoding="utf-8"
            )

    def _patch_kb(self, monkeypatch, tmp_path):
        """Point factlog.common module globals at tmp_path KB."""
        monkeypatch.setattr(fcommon, "ROOT", tmp_path)
        monkeypatch.setattr(fcommon, "POLICY_DIR", tmp_path / "policy")
        monkeypatch.setattr(fcommon, "CANDIDATES_CSV", tmp_path / "facts" / "candidates.csv")
        monkeypatch.setattr(fcommon, "ACCEPTED_DL", tmp_path / "facts" / "accepted.dl")
        monkeypatch.setattr(fcommon, "LOGIC_POLICY_DL", tmp_path / "policy" / "logic-policy.dl")

    def test_canonical_section_present_when_alias_file_exists(self, tmp_path, monkeypatch):
        self._make_kb(tmp_path, (
            "- `게재연도` -> `published_year`\n"
            "- `publication_year` -> `published_year`\n"
        ))
        self._patch_kb(monkeypatch, tmp_path)
        ctx = fcommon.schema_context()
        assert "Canonical relation names (prefer these):" in ctx
        # Python's default sort puts ASCII before Korean, so publication_year < 게재연도.
        assert "- published_year <- publication_year, 게재연도" in ctx

    def test_canonical_section_absent_when_no_alias_file(self, tmp_path, monkeypatch):
        """No alias file -> schema_context must NOT include a canonical section."""
        self._make_kb(tmp_path, alias_text=None)
        self._patch_kb(monkeypatch, tmp_path)
        ctx = fcommon.schema_context()
        assert "Canonical relation names" not in ctx
        assert "published_year" not in ctx

    def test_canonical_section_sorted_deterministic(self, tmp_path, monkeypatch):
        """Multiple canonicals appear in sorted order."""
        self._make_kb(tmp_path, (
            "- `게재연도` -> `published_year`\n"
            "- `author_name` -> `저자`\n"
        ))
        # Extend accepted.dl and candidates.csv with the extra relation.
        (tmp_path / "facts" / "accepted.dl").write_text(
            'relation("논문A", "게재연도", "2005").\n'
            'relation("논문A", "author_name", "김철수").\n',
            encoding="utf-8",
        )
        (tmp_path / "facts" / "candidates.csv").write_text(
            "subject,relation,object,source,status,confidence,note\n"
            "논문A,게재연도,2005,sources/test.md,confirmed,0.90,\n"
            "논문A,author_name,김철수,sources/test.md,confirmed,0.90,\n",
            encoding="utf-8",
        )
        self._patch_kb(monkeypatch, tmp_path)
        ctx = fcommon.schema_context()
        lines = ctx.splitlines()
        idx_published = next((i for i, ln in enumerate(lines) if "published_year" in ln and "<-" in ln), -1)
        idx_author = next((i for i, ln in enumerate(lines) if "저자" in ln and "<-" in ln), -1)
        assert idx_published != -1, "published_year canonical line not found"
        assert idx_author != -1, "저자 canonical line not found"
        # Python's default sort puts ASCII before Korean: published_year (p) < 저자.
        assert idx_published < idx_author, (
            f"Expected published_year line ({idx_published}) before 저자 line ({idx_author})"
        )


# ---------------------------------------------------------------------------
# #227 SLICE 1 commit 3: count() canonical symmetry
# ---------------------------------------------------------------------------

class TestCountCanonicalAcceptance:
    """count(S, canonical)? must validate the same way relation(S, canonical, O)? does."""

    def test_count_canonical_validates_ok(self, tmp_path, monkeypatch):
        """count("논문A", "published_year")? with alias file -> QUERY_OK (symmetry)."""
        _write_alias_file(tmp_path, (
            "- `게재연도` -> `published_year`\n"
            "- `publication_year` -> `published_year`\n"
        ))
        # Facts use surface variants; canonical itself never appears literally.
        facts = _make_facts([
            ("논문A", "게재연도", "2005"),
            ("논문B", "publication_year", "2007"),
        ])
        monkeypatch.setattr(fcommon, "POLICY_DIR", tmp_path / "policy")
        ok, code, reason = fcommon.classify_query(
            'count("논문A", "published_year")?', facts, policy_program=""
        )
        assert ok is True, f"expected ok=True, got code={code!r} reason={reason!r}"
        assert code == fcommon.QUERY_OK

    def test_count_canonical_variable_subject_validates_ok(self, tmp_path, monkeypatch):
        """count(S, "published_year")? with variable subject -> QUERY_OK."""
        _write_alias_file(tmp_path, "- `게재연도` -> `published_year`\n")
        facts = _make_facts([("논문A", "게재연도", "2005")])
        monkeypatch.setattr(fcommon, "POLICY_DIR", tmp_path / "policy")
        ok, code, reason = fcommon.classify_query(
            'count(S, "published_year")?', facts, policy_program=""
        )
        assert ok is True, f"code={code!r} reason={reason!r}"
        assert code == fcommon.QUERY_OK

    def test_count_unknown_relation_still_rejected(self, tmp_path, monkeypatch):
        """count with a non-canonical, non-accepted relation -> QUERY_RELATION_NOT_ACCEPTED."""
        _write_alias_file(tmp_path, "- `게재연도` -> `published_year`\n")
        facts = _make_facts([("논문A", "게재연도", "2005")])
        monkeypatch.setattr(fcommon, "POLICY_DIR", tmp_path / "policy")
        ok, code, reason = fcommon.classify_query(
            'count("논문A", "completely_unknown")?', facts, policy_program=""
        )
        assert ok is False
        assert code == fcommon.QUERY_RELATION_NOT_ACCEPTED

    def test_count_no_alias_file_unknown_relation_rejected(self, tmp_path, monkeypatch):
        """Without an alias file, count with unaccepted relation stays rejected."""
        (tmp_path / "policy").mkdir(parents=True, exist_ok=True)
        facts = _make_facts([("논문A", "게재연도", "2005")])
        monkeypatch.setattr(fcommon, "POLICY_DIR", tmp_path / "policy")
        ok, code, reason = fcommon.classify_query(
            'count("논문A", "published_year")?', facts, policy_program=""
        )
        assert ok is False
        assert code == fcommon.QUERY_RELATION_NOT_ACCEPTED


class TestCountCanonicalEvaluate:
    """count() canonical evaluation: distinct objects across canonical + variants."""

    def test_count_canonical_returns_distinct_object_count(self, tmp_path, monkeypatch):
        """count("논문A", "published_year")? counts distinct objects via variants.

        논문A has one fact under the variant 게재연도 -> 1 distinct object.
        """
        _write_alias_file(tmp_path, (
            "- `게재연도` -> `published_year`\n"
            "- `publication_year` -> `published_year`\n"
        ))
        facts = _make_facts([
            ("논문A", "게재연도", "2005"),
            ("논문B", "publication_year", "2007"),
        ])
        monkeypatch.setattr(fcommon, "POLICY_DIR", tmp_path / "policy")
        result = ask_router.evaluate('count("논문A", "published_year")?', facts)
        assert result["rows"] == [["1"]], f"expected [['1']], got {result['rows']}"
        assert result["count"] == 1

    def test_count_canonical_crosses_both_variants(self, tmp_path, monkeypatch):
        """count(S, "published_year")? with variable subject spans both variant rows.

        Two subjects, each with one distinct object -> count = 2.
        """
        _write_alias_file(tmp_path, (
            "- `게재연도` -> `published_year`\n"
            "- `publication_year` -> `published_year`\n"
        ))
        facts = _make_facts([
            ("논문A", "게재연도", "2005"),
            ("논문B", "publication_year", "2007"),
        ])
        monkeypatch.setattr(fcommon, "POLICY_DIR", tmp_path / "policy")
        result = ask_router.evaluate('count(S, "published_year")?', facts)
        assert result["rows"] == [["2"]], f"expected [['2']], got {result['rows']}"

    def test_count_canonical_deduplicates_same_object(self, tmp_path, monkeypatch):
        """Variant and canonical-name fact with the SAME object count once (DISTINCT).

        A subject has the same object stored under two different surface variants
        of the same canonical -> distinct count is 1, not 2.
        """
        _write_alias_file(tmp_path, (
            "- `게재연도` -> `published_year`\n"
            "- `publication_year` -> `published_year`\n"
        ))
        # Same object "2005" stored under two variants for the same subject.
        facts = _make_facts([
            ("논문A", "게재연도", "2005"),
            ("논문A", "publication_year", "2005"),
        ])
        monkeypatch.setattr(fcommon, "POLICY_DIR", tmp_path / "policy")
        result = ask_router.evaluate('count("논문A", "published_year")?', facts)
        assert result["rows"] == [["1"]], (
            f"same object under two variants must count once, got {result['rows']}"
        )

    def test_count_non_canonical_behavior_unchanged(self, tmp_path, monkeypatch):
        """count with a literal relation already in accepted facts -> unchanged behavior."""
        _write_alias_file(tmp_path, "- `게재연도` -> `published_year`\n")
        facts = _make_facts([
            ("논문A", "게재연도", "2005"),
            ("논문A", "게재연도", "2006"),  # same relation, different object
        ])
        monkeypatch.setattr(fcommon, "POLICY_DIR", tmp_path / "policy")
        result = ask_router.evaluate('count("논문A", "게재연도")?', facts)
        # 2 distinct objects under the literal relation name
        assert result["rows"] == [["2"]], f"expected [['2']], got {result['rows']}"


class TestCollisionNoDoubleCount:
    """Canonical name that ALSO equals a literally-stored relation -> no double-count.

    If "published_year" is both a canonical target in aliases AND literally stored
    as a relation in accepted facts, a relation(...) query must return each triple
    exactly once — the union of (canonical-match OR variant-match) rows with set
    semantics.
    """

    def test_relation_query_no_double_count_when_canonical_stored_literally(
        self, tmp_path, monkeypatch
    ):
        """relation(S, "published_year", O)? with rows stored under the canonical name
        AND under a variant -> each triple returned exactly once.

        Three distinct triples total: 1 stored as "published_year" (canonical),
        2 stored as surface variants. Query must return exactly 3 rows.
        """
        _write_alias_file(tmp_path, (
            "- `게재연도` -> `published_year`\n"
            "- `publication_year` -> `published_year`\n"
        ))
        facts = _make_facts([
            ("논문A", "published_year", "2003"),    # stored under canonical name itself
            ("논문B", "게재연도", "2005"),            # stored under Korean variant
            ("논문C", "publication_year", "2007"),  # stored under English variant
        ])
        monkeypatch.setattr(fcommon, "POLICY_DIR", tmp_path / "policy")
        rows = ask_router.evaluate_relation('relation(S, "published_year", O)?', facts)
        assert len(rows) == 3, (
            f"expected exactly 3 rows (no double-count), got {len(rows)}: {rows}"
        )
        # Each subject appears exactly once.
        subjects = [r[0] for r in rows]
        assert "논문A" in subjects
        assert "논문B" in subjects
        assert "논문C" in subjects

    def test_count_no_double_count_when_canonical_stored_literally(
        self, tmp_path, monkeypatch
    ):
        """count(S, "published_year")? with mixed literal/variant rows -> correct DISTINCT count.

        Same setup as above: 3 triples, all with distinct objects -> count = 3.
        """
        _write_alias_file(tmp_path, (
            "- `게재연도` -> `published_year`\n"
            "- `publication_year` -> `published_year`\n"
        ))
        facts = _make_facts([
            ("논문A", "published_year", "2003"),
            ("논문B", "게재연도", "2005"),
            ("논문C", "publication_year", "2007"),
        ])
        monkeypatch.setattr(fcommon, "POLICY_DIR", tmp_path / "policy")
        result = ask_router.evaluate('count(S, "published_year")?', facts)
        assert result["rows"] == [["3"]], (
            f"expected [['3']] distinct objects, got {result['rows']}"
        )


class TestAcceptedOnlyVariantRow:
    """A variant fact in accepted.dl with NO candidates.csv row -> [no extraction backing]."""

    def _make_kb_with_orphan_variant(self, tmp_path, alias_text: str):
        """KB where accepted.dl has a variant row not backed by candidates.csv."""
        for d in ("facts", "policy", "sources", "pages", "decisions"):
            (tmp_path / d).mkdir(parents=True, exist_ok=True)
        # accepted.dl has both rows; candidates.csv backs only one.
        (tmp_path / "facts" / "accepted.dl").write_text(
            'relation("논문A", "게재연도", "2005").\n'
            'relation("논문B", "publication_year", "2007").\n',
            encoding="utf-8",
        )
        # Only 논문A/게재연도 is in candidates — 논문B/publication_year has no CSV row.
        (tmp_path / "facts" / "candidates.csv").write_text(
            "subject,relation,object,source,status,confidence,note\n"
            "논문A,게재연도,2005,sources/paper-a.md,confirmed,0.90,\n",
            encoding="utf-8",
        )
        (tmp_path / "policy" / "relation-aliases.md").write_text(
            alias_text, encoding="utf-8"
        )

    def _patch_kb(self, monkeypatch, tmp_path):
        monkeypatch.setattr(fcommon, "ROOT", tmp_path)
        monkeypatch.setattr(fcommon, "POLICY_DIR", tmp_path / "policy")
        monkeypatch.setattr(fcommon, "CANDIDATES_CSV", tmp_path / "facts" / "candidates.csv")
        monkeypatch.setattr(fcommon, "ACCEPTED_DL", tmp_path / "facts" / "accepted.dl")
        monkeypatch.setattr(fcommon, "LOGIC_POLICY_DL", tmp_path / "policy" / "logic-policy.dl")

    def test_orphan_variant_row_shows_no_extraction_backing(self, tmp_path, monkeypatch):
        """A variant row in accepted.dl with no candidates.csv entry renders
        '[no extraction backing]' — the current correct behavior is locked in.

        render_engine_answer only annotates rows when signals is not None; passing
        fact_signals(facts) (built from candidates.csv) triggers the annotation for
        rows that have no matching candidate entry.
        """
        self._make_kb_with_orphan_variant(tmp_path, (
            "- `게재연도` -> `published_year`\n"
            "- `publication_year` -> `published_year`\n"
        ))
        self._patch_kb(monkeypatch, tmp_path)
        # evaluate_relation works on accepted facts (bare triples from accepted.dl).
        accepted = fcommon.load_accepted_facts()
        rows = ask_router.evaluate_relation('relation(S, "published_year", O)?', accepted)
        # Both rows should be returned (2 distinct triples).
        assert len(rows) == 2, f"expected 2 rows, got {len(rows)}: {rows}"
        # fact_signals is built from candidates (load_facts), not accepted facts —
        # candidates have status/source/confidence fields that engine_facts() needs.
        # Only 논문A/게재연도/2005 is in candidates -> 논문B row has no signal entry.
        candidates = fcommon.load_facts()
        signals = fcommon.fact_signals(candidates, root=tmp_path)
        rendered = ask_router.render_engine_answer(
            'relation(S, "published_year", O)?', rows, signals=signals
        )
        assert "[no extraction backing]" in rendered, (
            "orphan variant row (no candidates.csv entry) must show [no extraction backing]"
        )
