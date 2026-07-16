# SPDX-License-Identifier: Apache-2.0
"""A query constant meets a fact whatever unicode normal form each was authored in (#296).

Every query-value comparison routes through ``common._canonical_value`` (the single
chokepoint #213 set up: ``relation_row_matches``/``object_matches``/``classify_query``
all call it). It folded ``amount`` quoting but left an ordinary string in whatever
normal form it arrived in, so an NFD-stored relation or object — macOS text is routinely
NFD — never met an NFC-typed query constant, and the report/ask returned nothing about a
fact that was right there. Folding NFC once at that chokepoint makes both directions meet
without touching any per-path code, and is a no-op on NFC-only data.

Scope note: ``path`` queries answer against the engine's interned pairs
(``path_query_rows``), a raw comparison that does NOT pass through ``_canonical_value``;
that engine-intern path is the separate concern the issue flags and is not covered here.
"""
from __future__ import annotations

import unicodedata

import ask_router
import common
import pytest
import run_logic_check as rlc
from factlog.common import (
    _canonical_value,
    classify_query,
    object_matches,
    relation_row_matches,
)

nfc = lambda s: unicodedata.normalize("NFC", s)  # noqa: E731
nfd = lambda s: unicodedata.normalize("NFD", s)  # noqa: E731

REL = "연구유형"
OBJ = "관찰연구"
SUBJ = "P1"


def _row(subject, relation, object_):
    return {"subject": subject, "relation": relation, "object": object_}


def _args(subject, relation, object_):
    return [f'"{subject}"', f'"{relation}"', f'"{object_}"']


class TestRelationRowMatchesFoldsForms:
    """The shared predicate matches a query constant to a fact across NFC/NFD."""

    def test_nfd_relation_meets_nfc_query(self):
        row = _row(SUBJ, nfd(REL), nfd(OBJ))
        assert relation_row_matches(_args(SUBJ, nfc(REL), nfc(OBJ)), row)

    def test_nfc_relation_meets_nfd_query(self):
        row = _row(SUBJ, nfc(REL), nfc(OBJ))
        assert relation_row_matches(_args(SUBJ, nfd(REL), nfd(OBJ)), row)

    def test_a_genuinely_different_relation_still_does_not_match(self):
        row = _row(SUBJ, nfc(REL), nfc(OBJ))
        assert not relation_row_matches(_args(SUBJ, nfc("혈액형"), nfc(OBJ)), row)


class TestObjectMatchesFoldsForms:
    def test_nfd_object_meets_nfc_query(self):
        row = _row(SUBJ, nfc(REL), nfd(OBJ))
        assert object_matches(nfc(OBJ), row, None, _canonical_value)

    def test_nfc_object_meets_nfd_query(self):
        row = _row(SUBJ, nfc(REL), nfc(OBJ))
        assert object_matches(nfd(OBJ), row, None, _canonical_value)

    def test_a_different_object_still_does_not_match(self):
        row = _row(SUBJ, nfc(REL), nfc(OBJ))
        assert not object_matches(nfc("실험연구"), row, None, _canonical_value)


class TestCountMatchesFoldsForms:
    """A count is a relation query with a free object — same predicate, so an NFD
    fact is counted for an NFC query."""

    def test_count_over_nfd_facts_with_nfc_query(self):
        facts = [
            _row(SUBJ, nfd(REL), nfd(OBJ)),
            _row(SUBJ, nfd(REL), nfd("코호트연구")),
        ]
        args = common._query_args(f'count("{SUBJ}", "{nfc(REL)}")?')
        counted = {
            row["object"]
            for row in facts
            if relation_row_matches([args[0], args[1], "O"], row)
        }
        assert len(counted) == 2


class TestGateDoesNotReject:
    """The acceptance gate (classify_query) must not turn an NFD-stored object away
    from an NFC query. Its object check folds through _canonical_value, so both sides
    land on the same NFC form and the query resolves instead of being rejected."""

    def test_nfd_object_fact_passes_the_gate(self, tmp_path, monkeypatch):
        import factlog.common as fc

        (tmp_path / "policy").mkdir()
        monkeypatch.setattr(fc, "POLICY_DIR", tmp_path / "policy")
        facts = [{"subject": SUBJ, "relation": nfc(REL), "object": nfd(OBJ), "status": "accepted"}]
        ok, code, _reason = classify_query(
            f'relation("{SUBJ}", "{nfc(REL)}", "{nfc(OBJ)}")?', facts, policy_program=""
        )
        assert ok, code


class TestReportAskParity:
    """#213: the verifiable report and /factlog ask must resolve one query identically.
    Both delegate to relation_row_matches, so the NFC fold reaches them together — the
    two paths cannot fold an NFD relation/object differently."""

    @pytest.fixture
    def kb(self, tmp_path, monkeypatch):
        import factlog.common as fc

        (tmp_path / "policy").mkdir()
        monkeypatch.setattr(fc, "POLICY_DIR", tmp_path / "policy")
        return tmp_path

    def _both(self, query, facts):
        report = [tuple(r) for r in rlc.relation_results(query, facts)]
        ask = [tuple(r) for r in ask_router.evaluate_relation(query, facts)]
        return report, ask

    def test_nfd_relation_and_object_agree_in_both(self, kb):
        facts = [_row(SUBJ, nfd(REL), nfd(OBJ))]
        report, ask = self._both(f'relation(P, "{nfc(REL)}", "{nfc(OBJ)}")?', facts)
        assert report == ask == [(SUBJ, nfd(REL), nfd(OBJ))]

    def test_nfc_query_against_nfd_facts_is_not_the_empty_answer(self, kb):
        facts = [_row(SUBJ, nfd(REL), nfd(OBJ))]
        report, ask = self._both(f'relation(P, "{nfc(REL)}", "{nfc(OBJ)}")?', facts)
        assert report == ask
        assert len(report) == 1


class TestAmountRegression:
    """The amount canonicalisation this function already did must be unchanged, and it
    must now also fold an NFD-authored unit."""

    def test_nfc_unit_quoting_still_canonicalises(self):
        assert _canonical_value(nfc("amount(100,억)")) == 'amount(100,"억")'
        assert _canonical_value(nfc('amount(100,"억")')) == 'amount(100,"억")'

    def test_nfd_unit_now_canonicalises_to_the_same_form(self):
        assert _canonical_value(nfd("amount(100,억)")) == 'amount(100,"억")'

    def test_a_different_amount_is_not_equal(self):
        assert _canonical_value("amount(100,억)") != _canonical_value("amount(200,억)")


class TestNfcOnlyIsANoOp:
    """A KB already in NFC must compare byte-identically: folding an NFC string returns
    it unchanged, so nothing about existing (NFC) data moves."""

    def test_plain_nfc_string_passes_through_unchanged(self):
        assert _canonical_value(nfc(OBJ)) == nfc(OBJ)

    def test_nfc_string_is_its_own_fold(self):
        value = nfc(REL)
        assert _canonical_value(value) == value == unicodedata.normalize("NFC", value)


class TestFoldIsLoadBearing:
    """Red/green guard: without the NFC fold the NFD case does not match. Pinned by
    computing the pre-fix comparison (raw amount canonicalisation) directly."""

    def test_the_pre_fix_comparison_would_have_missed_the_nfd_case(self):
        # What _canonical_value did before #296: amount-only, no NFC.
        from factlog import literal_types

        pre_fix = lambda v: literal_types.canonical_amount(v) or v  # noqa: E731
        assert pre_fix(nfd(OBJ)) != pre_fix(nfc(OBJ))  # the bug: forms did not meet
        assert _canonical_value(nfd(OBJ)) == _canonical_value(nfc(OBJ))  # the fix
