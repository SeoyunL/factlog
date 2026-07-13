# SPDX-License-Identifier: Apache-2.0
"""classify_query's path branch must reject a wrong arity.

The count branch's arity guard is pinned by test_count_evaluate_arity.py (#257),
but the path branch's guard had no test of its own: flipping its `return False`
to `return True` left the entire suite green (unit, shell harnesses, golden and
smoke alike). A `path("A")?` would then have classified as a VALID query and gone
on to be answered, with nothing in the repo to catch it.
"""
from __future__ import annotations

import pytest

from factlog.common import QUERY_BAD_ARITY, QUERY_OK, classify_query

FACTS = [
    {"subject": "A", "relation": "uses", "object": "B", "status": "accepted"},
    {"subject": "B", "relation": "uses", "object": "C", "status": "accepted"},
]


def _classify(query: str):
    # policy_program="" keeps the developer's own logic-policy.dl out of the unit layer.
    return classify_query(query, FACTS, policy_program="")


@pytest.mark.parametrize(
    "query",
    [
        'path("A")?',  # one constant
        "path(X)?",  # one variable
        'path("A", "B", "C")?',  # three constants
        'path("A", "B", X)?',  # two constants and a variable
    ],
)
def test_a_path_query_that_is_not_binary_is_bad_arity(query):
    ok, code, _ = _classify(query)
    assert (ok, code) == (False, QUERY_BAD_ARITY)


def test_a_binary_path_query_still_passes():
    # regression anchor: the guard rejects arity, not paths.
    ok, code, _ = _classify('path("A", "C")?')
    assert (ok, code) == (True, QUERY_OK)
