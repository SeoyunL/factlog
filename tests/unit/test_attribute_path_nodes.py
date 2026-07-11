# SPDX-License-Identifier: Apache-2.0
"""Attribute relations do not become path nodes (#226).

The policy file `factlog init` hands the user says, in its own words:

    Objects of these relations are kept OUT of the entity set (so they do not show
    up as entities, path nodes, or count subjects) but remain valid, verifiable
    relation-query objects.

The entity list honoured that. The engine did not: `edge(S, O) :- relation(S, R, O)`
had no filter, so a dependency path hopped straight through a date —
`갑봇 -> 을서비스 -> 2030.1` — treating a literal as a waypoint. That is a false
guarantee in the file a user reads and trusts, about an artifact of the
deterministic engine.

The Python tracer (`dependency_graph`) must agree with the engine rule, because the
report asks the ENGINE whether a path exists and then asks the tracer to render it:
a divergence would print a route the engine says does not exist.
"""
from __future__ import annotations

import common
import factlog.common as fc
import pytest


@pytest.fixture
def kb(tmp_path, monkeypatch):
    """A KB whose policy dir the loaders actually read.

    Patch `factlog.common`, not `common`: the latter is a re-export shim, so
    rebinding POLICY_DIR there never reaches the module that reads it.
    """
    (tmp_path / "policy").mkdir()
    monkeypatch.setattr(fc, "POLICY_DIR", tmp_path / "policy")
    return tmp_path


def _row(subject, relation, object_):
    return {"subject": subject, "relation": relation, "object": object_, "status": "accepted"}


FACTS = [
    _row("갑봇", "통합", "을서비스"),
    _row("을서비스", "정식_운영", "2030.1"),   # attribute: the object is a literal
    _row("을서비스", "의존", "병모듈"),
]


class TestDependencyGraph:
    def test_a_literal_is_not_a_path_node(self, kb):
        (kb / "policy" / "attribute-relations.md").write_text("정식_운영\n", encoding="utf-8")
        assert common.dependency_path(FACTS, "갑봇", "2030.1") == []

    def test_entity_paths_still_resolve(self, kb):
        (kb / "policy" / "attribute-relations.md").write_text("정식_운영\n", encoding="utf-8")
        assert common.dependency_path(FACTS, "갑봇", "병모듈") == ["갑봇", "을서비스", "병모듈"]

    def test_without_the_declaration_the_literal_is_still_a_node(self, kb):
        # Undeclared = a first-class entity, by design. This pins that the fix keys
        # on the DECLARATION and does not start guessing what a literal looks like.
        assert common.dependency_path(FACTS, "갑봇", "2030.1") == ["갑봇", "을서비스", "2030.1"]


class TestEngineProgram:
    def test_the_edge_rule_excludes_attribute_relations(self):
        assert "!attr_rel(R)" in common.WIRELOG_PROGRAM

    def test_no_declarations_emit_no_attr_facts(self, kb):
        # A KB that declares nothing must produce a byte-identical program.
        assert common._attr_rel_facts() == ""

    def test_declared_relations_become_attr_rel_facts(self, kb):
        (kb / "policy" / "attribute-relations.md").write_text("정식_운영\n발행연도\n", encoding="utf-8")
        emitted = common._attr_rel_facts()
        assert 'attr_rel("정식_운영").' in emitted
        assert 'attr_rel("발행연도").' in emitted
