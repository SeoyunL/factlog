# SPDX-License-Identifier: Apache-2.0
"""Value-hierarchy subsumption in object matching (#211).

A cohort study IS an observational study. Without a declared hierarchy the two
are unrelated strings, so a query for the broader value silently misses every
row filed under a narrower one — the exact quiet omission this KB exists to
prevent. Declaring the hierarchy must fix the query WITHOUT rewriting any fact:
accepted.dl stays a 1:1 projection of the accepted candidate rows.
"""
from __future__ import annotations

import common
import pytest
import run_logic_check as rlc

HIERARCHY_MD = """\
# comment line is ignored
- 연구유형: 코호트연구 ⊂ 관찰연구
- 연구유형: 단면연구 <: 관찰연구
- 대상질환: `emphysema` < COPD
"""


@pytest.fixture
def kb(tmp_path):
    """A KB root; `value_hierarchy(root=...)` reads <root>/policy/value-hierarchy.md.

    The root argument (not a monkeypatched POLICY_DIR) is what the loader is
    designed for — and `tools/common.py` only re-exports names, so patching the
    constant there would not reach the module that actually reads it.
    """
    (tmp_path / "policy").mkdir()
    return tmp_path


def _row(subject, relation, object_):
    return {"subject": subject, "relation": relation, "object": object_}


FACTS = [
    _row("P1", "연구유형", "관찰연구"),
    _row("P2", "연구유형", "코호트연구"),
    _row("P3", "연구유형", "단면연구"),
    _row("P4", "연구유형", "RCT"),
    _row("P5", "대상질환", "emphysema"),
]


class TestParse:
    def test_absent_file_is_empty(self, kb):
        assert common.value_hierarchy(kb) == {}

    def test_parses_all_three_spellings(self, kb):
        (kb / "policy" / "value-hierarchy.md").write_text(HIERARCHY_MD, encoding="utf-8")
        h = common.value_hierarchy(kb)
        assert h["연구유형"]["코호트연구"] == {"관찰연구"}
        assert h["연구유형"]["단면연구"] == {"관찰연구"}
        assert h["대상질환"]["emphysema"] == {"COPD"}

    def test_ancestors_are_transitive(self, kb):
        (kb / "policy" / "value-hierarchy.md").write_text(
            "- r: a ⊂ b\n- r: b ⊂ c\n", encoding="utf-8"
        )
        assert common.value_hierarchy(kb)["r"]["a"] == {"b", "c"}

    def test_a_cycle_is_dropped_not_hung(self, kb):
        # Hand-authored policy: a bad line must not take the logic check down.
        (kb / "policy" / "value-hierarchy.md").write_text(
            "- r: a ⊂ b\n- r: b ⊂ a\n", encoding="utf-8"
        )
        h = common.value_hierarchy(kb)  # must terminate
        assert "a" not in h.get("r", {}).get("a", set())


class TestSubsumption:
    def test_broad_query_catches_narrow_rows(self, kb):
        (kb / "policy" / "value-hierarchy.md").write_text(HIERARCHY_MD, encoding="utf-8")
        h = common.value_hierarchy(kb)
        rows = rlc.relation_results('relation(P, "연구유형", "관찰연구")?', FACTS, h)
        assert {r[0] for r in rows} == {"P1", "P2", "P3"}

    def test_without_the_declaration_the_query_leaks(self, kb):
        # This is the #211 bug: the same query, no hierarchy → the two subtype
        # rows vanish. Pinned so the fix cannot be quietly reverted.
        rows = rlc.relation_results('relation(P, "연구유형", "관찰연구")?', FACTS, None)
        assert {r[0] for r in rows} == {"P1"}

    def test_subsumption_is_one_way(self, kb):
        (kb / "policy" / "value-hierarchy.md").write_text(HIERARCHY_MD, encoding="utf-8")
        h = common.value_hierarchy(kb)
        rows = rlc.relation_results('relation(P, "연구유형", "코호트연구")?', FACTS, h)
        assert {r[0] for r in rows} == {"P2"}  # NOT P1 (the broader row)

    def test_unrelated_value_is_untouched(self, kb):
        (kb / "policy" / "value-hierarchy.md").write_text(HIERARCHY_MD, encoding="utf-8")
        h = common.value_hierarchy(kb)
        rows = rlc.relation_results('relation(P, "연구유형", "RCT")?', FACTS, h)
        assert {r[0] for r in rows} == {"P4"}

    def test_hierarchy_is_scoped_to_its_relation(self, kb):
        # `emphysema ⊂ COPD` is declared for 대상질환 only; it must not leak into
        # another relation that happens to use the same value.
        (kb / "policy" / "value-hierarchy.md").write_text(HIERARCHY_MD, encoding="utf-8")
        h = common.value_hierarchy(kb)
        facts = [_row("P9", "언급질환", "emphysema")]
        assert rlc.relation_results('relation(P, "언급질환", "COPD")?', facts, h) == []

    def test_returned_rows_report_their_own_value(self, kb):
        # The row keeps its real object; subsumption widens the match, it does
        # not rewrite the fact.
        (kb / "policy" / "value-hierarchy.md").write_text(HIERARCHY_MD, encoding="utf-8")
        h = common.value_hierarchy(kb)
        rows = rlc.relation_results('relation("P2", "연구유형", "관찰연구")?', FACTS, h)
        assert rows == [("P2", "연구유형", "코호트연구")]


class TestObjectMatches:
    def test_normalizer_folds_surface_spelling(self, kb):
        h = {"r": {"child": {"PARENT"}}}
        row = _row("S", "r", "child")
        assert not common.object_matches("parent", row, h)
        assert common.object_matches("parent", row, h, str.lower)

    def test_no_hierarchy_is_exact_match(self):
        row = _row("S", "r", "child")
        assert common.object_matches("child", row, None)
        assert not common.object_matches("parent", row, None)
