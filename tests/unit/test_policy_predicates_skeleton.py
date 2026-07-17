# SPDX-License-Identifier: Apache-2.0
"""policy_predicates must see the same .decl set the reserved-head guard sees (#333).

policy_predicates used a ``^``-anchored regex (column 0 only), while
_assert_no_canonical_head scans a _scan_policy skeleton with no anchor. An INDENTED
``.decl`` was therefore REAL to the guard but INVISIBLE to policy_predicates, so
run_logic_check never queried that predicate and its findings vanished silently — the
fourth drifting parser the #226/#250 note warned about. Both now read the same skeleton.
"""
from __future__ import annotations

import pytest

import factlog.common as fcommon


class TestIndentedDeclIsVisible:
    def test_flush_left_decl_is_seen(self):
        assert fcommon.policy_predicates(".decl sneaky(x: symbol, r: symbol)\n") == {"sneaky"}

    def test_indented_decl_is_now_seen(self):
        """The #333 bug: a two-space-indented .decl used to yield an empty set."""
        policy = (
            "  .decl sneaky(x: symbol, r: symbol)\n"
            '  sneaky(X, "r") :- relation(X, "cites", _).\n'
        )
        assert "sneaky" in fcommon.policy_predicates(policy)

    def test_tab_indented_decl_is_seen(self):
        assert "sneaky" in fcommon.policy_predicates("\t.decl sneaky(x: symbol, r: symbol)\n")


class TestCommentsAndStringsAreNotDecls:
    def test_decl_in_line_comment_is_not_a_predicate(self):
        assert fcommon.policy_predicates("// .decl ghost(x: symbol, r: symbol)\n") == set()

    def test_decl_in_hash_comment_is_not_a_predicate(self):
        assert fcommon.policy_predicates("# .decl ghost(x: symbol, r: symbol)\n") == set()

    def test_decl_inside_a_string_literal_is_not_a_predicate(self):
        policy = (
            ".decl flag(x: symbol, r: symbol)\n"
            'flag(X, ".decl ghost(a: symbol)") :- relation(X, "a", _).\n'
        )
        assert fcommon.policy_predicates(policy) == {"flag"}


class TestParityWithReservedHeadGuard:
    """The two parsers must agree on what a .decl IS. Indentation is the case that split
    them: factlog itself treats an indented reserved .decl as real (the guard rejects it),
    so policy_predicates must treat an indented user .decl as real too."""

    def test_indented_reserved_decl_is_rejected_by_the_guard(self):
        with pytest.raises(fcommon.FactlogError):
            fcommon._assert_no_canonical_head("  .decl relation_alive(x: symbol)\n")

    def test_both_parsers_agree_on_an_indented_user_decl(self):
        policy = (
            "  .decl orphan(x: symbol, r: symbol)\n"
            '  orphan(X, "r") :- relation(X, "cites", _).\n'
        )
        # policy_predicates sees the indented user predicate ...
        assert "orphan" in fcommon.policy_predicates(policy)
        # ... and the guard, reading the same skeleton, does not falsely reject a
        # non-reserved indented .decl (parity in the other direction).
        fcommon._assert_no_canonical_head(policy)
