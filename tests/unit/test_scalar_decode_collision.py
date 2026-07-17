# SPDX-License-Identifier: Apache-2.0
"""An int64 scalar must not be decoded as an interned symbol (#120 prose rule).

The root cause is a SECOND layer redoing the FIRST layer's job from the value alone.
The engine's schema is the only thing that knows what a column means, and
``EasySession.step()`` applies it before we see a row (``_decode_row``): a ``symbol``
column arrives already decoded to ``str``, an ``int64`` column already an ``int``.

Measured against the real engine (pyrewire 1.0.3): for

    .decl priority_rank(subject: symbol, r: int64)
    .decl low_rank(subject: symbol, r: int64)
    relation("alpha", "is", "thing").
    priority_rank(S, 3) :- relation(S, "is", "thing").
    low_rank(S, R) :- priority_rank(S, R), R < 5.

``session.step()`` emits ``('low_rank', ('alpha', 3), 1)`` — ``'alpha'`` is ALREADY a
``str`` and ``3`` is ALREADY the correct ``int``.

``decode_wirelog_value`` (``factlog/common.py``) then re-decoded that row looking only
at the value: ``isinstance(value, int) and session._intern.contains_id(value)``. Nothing
in that test can distinguish a SYMBOL ID from a genuine ``int64`` value — and it never
needed to help, since a symbol column is already ``str`` and fails the ``isinstance``.
It could only harm: it rewrote the ``3`` into ``'beta'``. The head is arity-2, so it
renders as a normal policy finding — the report prints ``low_rank: alpha (beta)`` where
the truth is ``low_rank: alpha (3)``: a fabricated reason string on a real subject, with
no warning and a clean exit.

The scalar-free-head convention this relies on existed only as prose (next to
``_project_typed_relations``); the policy-load guard accepted an ``int64`` column.
Corruption only shows once the KB interns more symbols than the scalar's value, so small
ordinal ranks are the dangerous case and a large date like ``20300101`` passes through
unharmed — which is why this survives casual testing.
"""
from __future__ import annotations

import pytest

from common import decode_wirelog_value

try:  # pragma: no cover - environment-dependent
    import pyrewire  # noqa: F401

    _HAVE_ENGINE = True
except ImportError:  # pragma: no cover
    _HAVE_ENGINE = False


class FakeIntern:
    """The two methods decode_wirelog_value calls on session._intern."""

    def __init__(self, symbols):
        self._symbols = list(symbols)

    def contains_id(self, value):
        return 0 <= value < len(self._symbols)

    def lookup(self, value):
        return self._symbols[value]


class FakeSession:
    def __init__(self, symbols):
        self._intern = FakeIntern(symbols)


class TestScalarIsNotRewrittenAsASymbol:
    def test_small_scalar_collides_with_a_symbol_id(self):
        session = FakeSession(["alpha", "beta", "published_year", "gamma", "delta"])
        assert decode_wirelog_value(session, 3) == 3, (
            "an int64 column value was rewritten into an interned symbol"
        )

    def test_decoded_symbol_passes_through(self):
        """step() decodes symbol columns; the decoder must not re-handle them."""
        session = FakeSession(["alpha", "beta", "gamma"])
        assert decode_wirelog_value(session, "beta") == "beta"

    def test_large_scalar_is_unharmed(self):
        """Why this hides: a date-shaped scalar exceeds the intern table and passes."""
        session = FakeSession(["alpha", "beta", "gamma"])
        assert decode_wirelog_value(session, 20300101) == 20300101

    def test_bool_is_not_looked_up_as_an_id(self):
        """bool is an int subclass, so True indexes the table as id 1."""
        session = FakeSession(["alpha", "beta", "gamma"])
        assert decode_wirelog_value(session, True) is True


@pytest.mark.skipif(not _HAVE_ENGINE, reason="pyrewire not installed")
class TestAgainstTheRealEngine:
    """The authority: what the engine's schema decoding actually hands the decoder."""

    def _session(self):
        from pyrewire import EasySession

        program = (
            ".decl relation(subject: symbol, rel: symbol, object: symbol)\n"
            ".decl priority_rank(subject: symbol, r: int64)\n"
            ".decl low_rank(subject: symbol, r: int64)\n"
            'relation("alpha", "is", "thing").\n'
            'priority_rank(S, 3) :- relation(S, "is", "thing").\n'
            "low_rank(S, R) :- priority_rank(S, R), R < 5.\n"
        )
        session = EasySession(program)
        for value in ["alpha", "beta", "published_year", "gamma", "delta"]:
            session.intern(value)
        return session

    def test_engine_emits_a_raw_int_for_an_int64_column(self):
        session = self._session()
        try:
            rows = {name: row for name, row, diff in session.step() if diff > 0}
            assert "low_rank" in rows, rows
            assert rows["low_rank"][1] == 3, (
                f"expected the raw scalar 3, got {rows['low_rank'][1]!r}"
            )
        finally:
            session.close()

    def test_engine_decodes_a_symbol_column_to_str(self):
        """The premise of the fix: the schema, not the decoder, resolves symbols.

        decode_wirelog_value passes values through because step() has ALREADY typed
        them. If a future engine stopped decoding symbol columns and handed back raw
        ids, that pass-through would silently print ints where names belong — so pin
        the contract here rather than trusting the pyproject pin alone.
        """
        session = self._session()
        try:
            rows = {name: row for name, row, diff in session.step() if diff > 0}
            subject = rows["low_rank"][0]
            assert isinstance(subject, str), (
                f"step() handed back {subject!r} ({type(subject).__name__}); the "
                "engine no longer decodes symbol columns and decode_wirelog_value's "
                "pass-through is no longer sound"
            )
            assert subject == "alpha"
        finally:
            session.close()

    def test_report_does_not_render_a_fabricated_reason(self):
        session = self._session()
        try:
            rows = {name: row for name, row, diff in session.step() if diff > 0}
            decoded = [decode_wirelog_value(session, v) for v in rows["low_rank"]]
            assert decoded == ["alpha", 3], (
                f"the report would print low_rank: {decoded[0]} ({decoded[1]}) "
                "instead of low_rank: alpha (3)"
            )
        finally:
            session.close()
