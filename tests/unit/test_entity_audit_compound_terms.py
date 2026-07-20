# SPDX-License-Identifier: Apache-2.0
"""entity_audit must not pair typed literals with each other (#386).

`text-to-fact.md` mandates compound-term notation for typed values — `date(2020)`,
`number(19)`. entity_audit only knew the pre-normalization prose forms, so those
values stayed in the entity set, `_tokens` split the wrapper name off, and `date`
became a token shared by every date: all C(n,2) date pairs surfaced as
fragmentation candidates and buried the real ones. These tests pin BOTH halves —
the wrapper pairs are gone AND a genuine candidate still fires.
"""
from __future__ import annotations

import entity_audit


def _row(subject, relation, object_, status="accepted"):
    return {
        "subject": subject,
        "relation": relation,
        "object": object_,
        "status": status,
    }


def _shared_token_pairs(found):
    return [c for c in found["clusters"] if c[2].startswith("shared token")]


class TestCompoundTermsAreNotEntities:
    def test_dates_and_numbers_never_pair_with_each_other(self):
        facts = [
            _row("P1", "published_year", "date(1998)"),
            _row("P2", "published_year", "date(2020)"),
            _row("P3", "published_year", "date(2023)"),
            _row("P4", "published_year", "date(2025)"),
            _row("P1", "cited_by_count", "number(19)"),
            _row("P2", "cited_by_count", "number(92)"),
            _row("P3", "cited_by_count", "number(228)"),
            _row("P4", "cited_by_count", "number(348)"),
        ]
        found = entity_audit.audit(facts)

        assert _shared_token_pairs(found) == []
        for value in ("date(2020)", "number(19)"):
            assert value not in found["entities"]

    def test_every_wrapper_name_is_covered(self):
        # The names come from literal_types.TYPES; each one must be recognized.
        facts = [
            _row("P1", "attr", "date(2020,3,8)"),
            _row("P2", "attr", "number(2.5)"),
            _row("P3", "attr", "ordinal(3)"),
            _row("P4", "attr", 'amount(100,"억")'),
        ]
        found = entity_audit.audit(facts)

        assert found["entities"] == ["P1", "P2", "P3", "P4"]
        assert found["clusters"] == []

    def test_an_undeclared_relation_still_gets_the_declare_advice(self):
        # Dropping them from the entity set must not make them silent: the point
        # of the tool is to say "declare this relation".
        facts = [_row("P1", "published_year", "date(2020)")]
        found = entity_audit.audit(facts)

        assert found["literal_suspects"]["published_year"] == {"date(2020)"}


class TestRealCandidatesSurvive:
    def test_substring_contained_pair_is_still_reported(self):
        facts = [
            _row("Neurosymbolic Value-Inspired AI (Why, What, and How)", "topic", "AI"),
            _row("Value-Inspired AI", "topic", "AI"),
            _row("P1", "published_year", "date(2020)"),
            _row("P2", "published_year", "date(2023)"),
        ]
        found = entity_audit.audit(facts)

        assert _shared_token_pairs(found) == []
        reasons = {c[2] for c in found["clusters"]}
        assert "substring-contained" in reasons

    def test_a_shared_token_between_real_entities_is_still_reported(self):
        facts = [
            _row("Samplebot Research Lab", "topic", "AI"),
            _row("Samplebot Institute", "topic", "AI"),
        ]
        found = entity_audit.audit(facts)

        assert [c[2] for c in _shared_token_pairs(found)] == ["shared token ['Samplebot']"]

    def test_a_bare_paren_value_is_not_mistaken_for_a_compound_term(self):
        # Only the declared wrapper names count; an ordinary parenthetical entity
        # must stay an entity.
        facts = [_row("P1", "topic", "기타(IL-10)")]
        found = entity_audit.audit(facts)

        assert "기타(IL-10)" in found["entities"]
