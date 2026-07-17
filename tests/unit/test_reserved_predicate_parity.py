# SPDX-License-Identifier: Apache-2.0
"""The reserved-predicate sets must cover every engine .decl (#332/#334).

WIRELOG_PROGRAM declares six predicates. A generated bullet, a typed-relation alias,
or a hand-authored policy .decl that HEADS one of them is silently mishandled by the
engine with rc=0. That concept lives in FOUR hand-managed sets, and hand-managed sets
drift: #332 is where relation_alive (the #308 witness) was never added to the
generator's RESERVED_PREDICATES and review_required (declared by no .decl) lingered.
These tests pin the coverage so a future engine predicate cannot slip in unguarded.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

import factlog.common as fcommon

sys.path.insert(0, str(Path.cwd() / "tools"))
import generate_logic_policy as glp  # noqa: E402


def _wirelog_decls() -> set[str]:
    return set(
        re.findall(r"^\.decl\s+([a-z_][a-z0-9_]*)\(", fcommon.WIRELOG_PROGRAM, re.MULTILINE)
    )


class TestReservedPredicatesCoverEngineDecls:
    def test_reserved_predicates_superset_of_wirelog_decls(self):
        """Every predicate the engine declares must be reserved from generated heads."""
        decls = _wirelog_decls()
        assert decls, "WIRELOG_PROGRAM declared no .decl — regex or program changed"
        missing = decls - glp.RESERVED_PREDICATES
        assert not missing, f"RESERVED_PREDICATES misses engine .decl(s): {sorted(missing)}"

    def test_relation_alive_is_reserved(self):
        """The #308 witness predicate is explicitly covered (the drift #332 fixes)."""
        assert "relation_alive" in glp.RESERVED_PREDICATES

    def test_review_required_is_not_reserved(self):
        """review_required is declared by no .decl; keeping it only blocked a valid name."""
        assert "review_required" not in glp.RESERVED_PREDICATES


class TestGeneratorRejectsReservedHeadBullet:
    def test_relation_alive_bullet_is_rejected(self):
        """A bullet whose inferred predicate is relation_alive must fail at GENERATION.

        Otherwise it compiles to `.decl relation_alive(entity, reason)` — an arity-2
        re-declaration of the engine's arity-1 witness that pyrewire parses with rc=0,
        so main() writes the file and then EVERY load rejects it as a reserved-predicate
        clash: the KB is bricked until the generated output is hand-edited (#332).
        """
        payload = {
            "rules": [
                {
                    "predicate": "relation_alive",
                    "reason": "hijack",
                    "conditions": [{"relation": "cites"}],
                }
            ]
        }
        with pytest.raises(ValueError, match="relation_alive"):
            glp.normalized_rules(payload)

    def test_an_ordinary_policy_predicate_still_compiles(self):
        """Control: a non-reserved predicate name is still accepted."""
        payload = {
            "rules": [
                {
                    "predicate": "conflict",
                    "reason": "dup",
                    "conditions": [{"relation": "cites"}],
                }
            ]
        }
        rules = glp.normalized_rules(payload)
        assert rules[0]["predicate"] == "conflict"


class TestFourConsumerSetsShareOneSource:
    """The four sets that encode "an engine-declared predicate" now derive from
    common._engine_decl_predicates (#334). This pins each consumer to that single
    source so none can drift the way #332 (relation_alive) and #334 (canonical) did.
    Removing the derivation and re-hardcoding any one of them reopens the divergence.
    """

    def test_engine_source_is_the_six_wirelog_decls(self):
        engine = fcommon._engine_decl_predicates()
        assert engine == _wirelog_decls()
        assert engine == {
            "relation",
            "canonical",
            "attr_rel",
            "edge",
            "path",
            "relation_alive",
        }

    def test_generator_reserved_set_is_the_engine_set(self):
        """Consumer 1: the generator's RESERVED_PREDICATES."""
        assert set(glp.RESERVED_PREDICATES) == fcommon._engine_decl_predicates()

    def test_typed_alias_reserved_set_covers_the_engine_set(self):
        """Consumer 2: the typed-relation alias guard. canonical is the #334 miss."""
        reserved = fcommon._typed_reserved_names(set(), set())
        assert reserved >= fcommon._engine_decl_predicates()
        assert "canonical" in reserved

    def test_policy_predicates_filters_every_engine_name(self):
        """Consumer 3: policy_predicates' built_in filter. Before #334, canonical and
        relation_alive were NOT filtered and would have been walked as findings."""
        engine = fcommon._engine_decl_predicates()
        text = "".join(f".decl {n}(a: symbol, b: symbol)\n" for n in engine)
        text += ".decl mypred(a: symbol, b: symbol)\n"
        assert fcommon.policy_predicates(text) == {"mypred"}

    def test_reserved_head_guard_covers_the_engine_set(self):
        """Consumer 4: _assert_no_canonical_head. Every engine predicate is rejected
        as a head — the five fully-reserved via the shared message, relation via its
        own bare-fact-aware branch."""
        for name in fcommon._engine_decl_predicates():
            with pytest.raises(fcommon.FactlogError):
                fcommon._assert_no_canonical_head(f".decl {name}(a: symbol, b: symbol)\n")

    def test_canonical_is_now_reserved_everywhere(self):
        """The specific #334 symptom: canonical was accepted as a typed alias and a
        policy finding. It must now be reserved in every consumer."""
        assert "canonical" in glp.RESERVED_PREDICATES
        assert "canonical" in fcommon._typed_reserved_names(set(), set())
        assert "canonical" not in fcommon.policy_predicates(
            ".decl canonical(a: symbol, b: symbol)\n"
        )
        with pytest.raises(fcommon.FactlogError):
            fcommon._assert_no_canonical_head(".decl canonical(a: symbol, b: symbol)\n")
