# SPDX-License-Identifier: Apache-2.0
"""Regression tests for run_logic_check query evaluation (#99).

A comma inside a quoted object literal must not be split into extra args.
With the old naive ``split(",")`` parser these queries produced 0 rows even
though the fact exists; after delegating to common's string-aware parser they
resolve correctly.
"""
from __future__ import annotations

import run_logic_check as rlc


def _fact(subject, relation, object_):
    return {"subject": subject, "relation": relation, "object": object_}


class TestRelationResultsCommaLiteral:
    def test_object_with_comma_matches(self):
        facts = [_fact("A", "born_in", "Paris, France")]
        rows = rlc.relation_results('relation("A", "born_in", "Paris, France")?', facts)
        assert rows == [("A", "born_in", "Paris, France")]

    def test_object_with_comma_does_not_match_different_value(self):
        facts = [_fact("A", "born_in", "Paris, France")]
        rows = rlc.relation_results('relation("A", "born_in", "Lyon, France")?', facts)
        assert rows == []

    def test_variable_object_binds_comma_value(self):
        facts = [_fact("A", "born_in", "Paris, France")]
        rows = rlc.relation_results('relation("A", "born_in", O)?', facts)
        assert rows == [("A", "born_in", "Paris, France")]

    def test_plain_three_arg_still_works(self):
        facts = [_fact("A", "knows", "B")]
        rows = rlc.relation_results('relation("A", "knows", "B")?', facts)
        assert rows == [("A", "knows", "B")]


def _row(status):
    return {"subject": "A", "relation": "r", "object": "B", "status": status}


class TestStatusWarnings:
    """Status vocabulary of the logic report (#208).

    `factlog reject`/`amend` retires a row as `superseded`. That is a known
    status, so the report must stay silent about it — warning per retired row
    made the report noisier the more review had been done. A typo must still
    warn.
    """

    def test_superseded_is_silent(self):
        assert rlc.status_warnings([_row("superseded")]) == []

    def test_engine_and_review_statuses_are_silent(self):
        rows = [_row(s) for s in ("confirmed", "accepted", "needs_review", "candidate")]
        assert rlc.status_warnings(rows) == []

    def test_unrecognised_status_still_warns(self):
        warnings = rlc.status_warnings([_row("bogus")])
        assert warnings == ["unknown status treated as non-engine input: bogus"]

    def test_warns_once_per_offending_row_only(self):
        rows = [_row("superseded"), _row("bogus"), _row("accepted")]
        assert len(rlc.status_warnings(rows)) == 1

    def test_vocabulary_follows_common(self):
        # Pins the derive-don't-restate rule: extending common's vocabulary must
        # extend this consumer, which is exactly what #208 broke.
        import common

        for status in common.KNOWN_STATUSES:
            assert rlc.status_warnings([_row(status)]) == [], status

    def test_every_status_the_cli_writes_is_known(self):
        # accept/reject/amend write these; none may be reported as unknown.
        import common

        assert {"accepted", "superseded"} <= set(common.KNOWN_STATUSES)
