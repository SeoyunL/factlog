# SPDX-License-Identifier: Apache-2.0
"""The acceptance gate must fold unicode forms the SAME way the matcher does (#296).

#296 folded the query-value comparison chokepoint (``_canonical_value``), so an
NFD-stored relation/object meets an NFC-typed query constant in the MATCHER
(``relation_row_matches``). But ``classify_query`` — the GATE that decides route=engine
vs route=wiki — compared subject/relation/entity membership against the raw fact-derived
sets (``entity_set``/``allowed_relations``). So for an NFD fact + NFC query the matcher
matched the row while the gate called the constant "not accepted" and routed to wiki:
the gate and matcher disagreed, breaking the #213 parity guarantee for NFD-authored KBs.

The fix folds BOTH sides of each membership test inside the gate only (the set builders
stay raw, so the engine emitter / dependency_graph / vocab / display provenance are
byte-unchanged). ``path`` is deliberately left raw on both gate and matcher — it is
self-consistent there and is tracked separately as #299.
"""
from __future__ import annotations

import unicodedata

import ask_router
import common
import pytest
import run_logic_check as rlc
from factlog.common import (
    allowed_relations,
    classify_query,
    entity_set,
    value_set,
)

nfc = lambda s: unicodedata.normalize("NFC", s)  # noqa: E731
nfd = lambda s: unicodedata.normalize("NFD", s)  # noqa: E731

REL = "연구유형"
OBJ = "관찰연구"
SUBJ = "P1"

# requires_review is a policy query predicate once declared; the text is all
# classify_query reads to recognise it (the .decl name).
POLICY_DECL = ".decl requires_review(entity: symbol, reason: symbol)\n"


def _row(subject, relation, object_):
    return {"subject": subject, "relation": relation, "object": object_, "status": "accepted"}


@pytest.fixture
def kb(tmp_path, monkeypatch):
    """Empty policy dir so the modules that resolve POLICY_DIR lazily see no aliases."""
    import factlog.common as fc

    (tmp_path / "policy").mkdir()
    monkeypatch.setattr(fc, "POLICY_DIR", tmp_path / "policy")
    return tmp_path


class TestRouterRoutesEngineAcrossForms:
    """The core regression: NFD fact + NFC query must route to ENGINE, not wiki.
    Before the gate fold these routed to wiki (the matcher matched but the gate
    rejected the constant). Driven through ask_router.classify — the real routing
    path — for relation, count and policy predicates, both form directions."""

    def test_relation_nfd_fact_nfc_query_routes_engine(self, kb):
        facts = [_row(SUBJ, nfd(REL), nfd(OBJ))]
        q = f'relation("{SUBJ}", "{nfc(REL)}", "{nfc(OBJ)}")?'
        assert ask_router.classify(q, facts)["route"] == "engine"

    def test_relation_nfc_fact_nfd_query_routes_engine(self, kb):
        facts = [_row(SUBJ, nfc(REL), nfc(OBJ))]
        q = f'relation("{SUBJ}", "{nfd(REL)}", "{nfd(OBJ)}")?'
        assert ask_router.classify(q, facts)["route"] == "engine"

    def test_count_nfd_fact_nfc_query_routes_engine(self, kb):
        facts = [_row(SUBJ, nfd(REL), nfd(OBJ))]
        q = f'count("{SUBJ}", "{nfc(REL)}")?'
        assert ask_router.classify(q, facts)["route"] == "engine"

    def test_policy_nfd_fact_nfc_query_routes_engine(self, kb, monkeypatch):
        monkeypatch.setattr(ask_router, "_policy_program_optional", lambda: POLICY_DECL)
        # A Hangul subject that actually differs NFC vs NFD (unlike an ASCII id), so
        # the fold is what carries the NFC query to the NFD-stored entity.
        subject = "갑을병"
        facts = [_row(nfd(subject), nfd(REL), nfd(OBJ))]
        q = f'requires_review("{nfc(subject)}", R)?'
        assert ask_router.classify(q, facts)["route"] == "engine"


class TestGateAcceptsAllForms:
    """classify_query directly: subject/relation/entity membership passes for every
    normal-form combination, so the gate never turns a form-variant constant away."""

    def _classify(self, q, facts, policy=""):
        return classify_query(q, facts, policy_program=policy)

    def test_relation_subject_and_relation_membership_both_directions(self, kb):
        nfd_facts = [_row(SUBJ, nfd(REL), nfd(OBJ))]
        ok, code, _ = self._classify(f'relation("{SUBJ}", "{nfc(REL)}", "{nfc(OBJ)}")?', nfd_facts)
        assert ok, code
        nfc_facts = [_row(SUBJ, nfc(REL), nfc(OBJ))]
        ok, code, _ = self._classify(f'relation("{SUBJ}", "{nfd(REL)}", "{nfd(OBJ)}")?', nfc_facts)
        assert ok, code

    def test_count_subject_and_relation_membership_both_directions(self, kb):
        nfd_facts = [_row(SUBJ, nfd(REL), nfd(OBJ))]
        ok, code, _ = self._classify(f'count("{SUBJ}", "{nfc(REL)}")?', nfd_facts)
        assert ok, code
        nfc_facts = [_row(SUBJ, nfc(REL), nfc(OBJ))]
        ok, code, _ = self._classify(f'count("{SUBJ}", "{nfd(REL)}")?', nfc_facts)
        assert ok, code

    def test_policy_entity_membership_both_directions(self, kb):
        nfd_facts = [_row(SUBJ, nfd(REL), nfd(OBJ))]
        ok, code, _ = self._classify(f'requires_review("{nfc(SUBJ)}", R)?', nfd_facts, POLICY_DECL)
        assert ok, code
        # An entity that is itself NFD in the query against an NFC-stored subject.
        subj_nfd_stored = [_row(nfc("가나다"), nfc(REL), nfc(OBJ))]
        ok, code, _ = self._classify(f'requires_review("{nfd("가나다")}", R)?', subj_nfd_stored, POLICY_DECL)
        assert ok, code


class TestRouteAndAnswerAgree:
    """#213 restored end to end: once the gate routes to engine, the report and ask
    return the SAME rows for the same NFD-fact/NFC-query question."""

    def _both(self, query, facts):
        report = [tuple(r) for r in rlc.relation_results(query, facts)]
        ask = [tuple(r) for r in ask_router.evaluate_relation(query, facts)]
        return report, ask

    def test_relation_routes_engine_and_report_matches_ask(self, kb):
        facts = [_row(SUBJ, nfd(REL), nfd(OBJ))]
        q = f'relation(P, "{nfc(REL)}", "{nfc(OBJ)}")?'
        assert ask_router.classify(q, facts)["route"] == "engine"
        report, ask = self._both(q, facts)
        assert report == ask == [(SUBJ, nfd(REL), nfd(OBJ))]

    def test_count_routes_engine_and_report_count_matches_ask(self, kb):
        facts = [_row(SUBJ, nfd(REL), nfd(OBJ)), _row(SUBJ, nfd(REL), nfd("코호트연구"))]
        q = f'count("{SUBJ}", "{nfc(REL)}")?'
        assert ask_router.classify(q, facts)["route"] == "engine"
        args = common._query_args(q)
        report_objects = {
            row["object"]
            for row in facts
            if common.relation_row_matches([args[0], args[1], "O"], row, {}, None)
        }
        ask = ask_router.evaluate(q, facts)
        assert len(report_objects) == ask["count"] == 2


class TestNoOverAcceptance:
    """The fold must not make an UNKNOWN constant accepted — it only unifies forms of
    the same value, so a genuinely-absent entity/relation is still rejected (route=wiki)."""

    def test_unknown_subject_is_still_rejected(self, kb):
        facts = [_row(SUBJ, nfd(REL), nfd(OBJ))]
        q = f'relation("없는주체", "{nfc(REL)}", "{nfc(OBJ)}")?'
        assert ask_router.classify(q, facts)["route"] == "wiki"

    def test_unknown_relation_is_still_rejected(self, kb):
        facts = [_row(SUBJ, nfd(REL), nfd(OBJ))]
        q = f'relation("{SUBJ}", "없는관계", "{nfc(OBJ)}")?'
        assert ask_router.classify(q, facts)["route"] == "wiki"


class TestNfcOnlyIsUnchanged:
    """A KB already in NFC keeps routing exactly as before — the fold is a no-op on it."""

    def test_nfc_only_relation_routes_engine(self, kb):
        facts = [_row(SUBJ, nfc(REL), nfc(OBJ))]
        q = f'relation("{SUBJ}", "{nfc(REL)}", "{nfc(OBJ)}")?'
        assert ask_router.classify(q, facts)["route"] == "engine"


class TestSetBuildersStayRaw:
    """The fold lives INSIDE the gate; the shared set builders must still return the
    raw stored form (NFD preserved), so the engine emitter / vocab / display that read
    them are byte-unchanged. If a builder had been folded these would fail."""

    def test_entity_set_preserves_nfd(self, kb):
        facts = [_row(SUBJ, nfd(REL), nfd(OBJ))]
        ents = entity_set(facts)
        assert nfd(OBJ) in ents
        assert nfc(OBJ) not in ents  # the builder did NOT fold to NFC

    def test_allowed_relations_preserves_nfd(self, kb):
        facts = [_row(SUBJ, nfd(REL), nfd(OBJ))]
        rels = allowed_relations(facts)
        assert nfd(REL) in rels
        assert nfc(REL) not in rels

    def test_value_set_preserves_nfd(self, kb):
        facts = [_row(SUBJ, nfd(REL), nfd(OBJ))]
        vals = value_set(facts)
        assert nfd(OBJ) in vals
        assert nfc(OBJ) not in vals


class TestGateFoldIsLoadBearing:
    """Red/green without a source revert: the RAW membership the gate used before this
    change misses the NFD case (constant absent from the raw set), yet the folded gate
    now accepts it. Pins that the fold — not something else — is what routes it engine."""

    def test_raw_membership_would_miss_but_folded_gate_accepts(self, kb):
        facts = [_row(SUBJ, nfd(REL), nfd(OBJ))]
        # What the gate did before #296's rework: raw `constant not in entity_set`.
        assert nfc(OBJ) not in entity_set(facts)  # raw check would reject the NFC constant
        assert nfc(REL) not in allowed_relations(facts)
        # The folded gate routes the same NFD fact / NFC query to the engine.
        q = f'relation("{SUBJ}", "{nfc(REL)}", "{nfc(OBJ)}")?'
        assert ask_router.classify(q, facts)["route"] == "engine"
