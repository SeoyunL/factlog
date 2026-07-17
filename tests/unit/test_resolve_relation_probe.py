# SPDX-License-Identifier: Apache-2.0
"""resolve_relation is THE alias probe — convergence guard (#343).

#307/#310/#314/#324/#325/#326 were each the same defect one axis at a time: a
comparison or lookup that forgot to fold NFC before probing the NFC-keyed alias
map, so mixed-spelling data split silently. The structural fix is not one more
axis but removing the ABILITY to write the raw probe: `resolve_relation(name,
aliases)` folds NFC once, and the sites that used a bare `aliases.get(...)` route
through it.

This is a behaviour-preserving refactor, so its guard is twofold:

* the probe folds correctly (an NFD name resolves exactly as its NFC twin);
* the converged call sites no longer carry a raw `aliases.get(` — a reintroduced
  raw probe is the exact regression #343 exists to make impossible. #324's
  membership fold (`NFC(row["relation"]) in variants`) is NOT a probe (no
  `aliases.get`), so it is deliberately outside this convergence.
"""
from __future__ import annotations

import inspect
import unicodedata

import common
from factlog.common import resolve_relation

nfc = lambda s: unicodedata.normalize("NFC", s)  # noqa: E731
nfd = lambda s: unicodedata.normalize("NFD", s)  # noqa: E731

RAW = "게재연도"  # alias key, stored NFC in the map
ALIASES = {nfc(RAW): "published_year"}


class TestProbeFoldsNfc:
    def test_nfc_key_resolves_to_canonical(self):
        assert resolve_relation(nfc(RAW), ALIASES) == "published_year"

    def test_nfd_name_folds_and_resolves(self):
        assert resolve_relation(nfd(RAW), ALIASES) == "published_year"

    def test_nfc_and_nfd_forms_resolve_identically(self):
        assert resolve_relation(nfc(RAW), ALIASES) == resolve_relation(nfd(RAW), ALIASES)

    def test_unknown_name_returns_itself_verbatim(self):
        """A name not in the map falls through to itself in its ORIGINAL form —
        the fold only decides the lookup key, it must not coerce the fallback."""
        stranger = nfd("미등록관계")
        assert resolve_relation(stranger, ALIASES) == stranger

    def test_empty_map_returns_name_verbatim(self):
        stranger = nfd(RAW)
        assert resolve_relation(stranger, {}) == stranger

    def test_matches_the_bare_probe_it_replaces(self):
        """Behaviour identity with the inline it converged: `aliases.get(NFC(name), name)`."""
        for name in (nfc(RAW), nfd(RAW), "published_year", nfd("없음")):
            assert resolve_relation(name, ALIASES) == ALIASES.get(nfc(name), name)


class TestCallSitesRouteThroughTheProbe:
    """The two sites #343 converges — the matcher's variable-relation resolution
    and the hierarchy-warning relation key — must go THROUGH resolve_relation and
    carry no raw `aliases.get(` of their own. A raw probe reappearing here is the
    per-axis regression this refactor removes the ability to make."""

    def test_relation_row_matches_uses_the_probe_not_a_raw_get(self):
        src = inspect.getsource(common.relation_row_matches)
        assert "resolve_relation(" in src
        assert "aliases.get(" not in src

    def test_value_hierarchy_warnings_uses_the_probe_not_a_raw_get(self):
        src = inspect.getsource(common.value_hierarchy_warnings)
        assert "resolve_relation(" in src
        assert "aliases.get(" not in src

    def test_probe_is_the_only_bare_alias_get_in_the_module(self):
        """Module-wide: the sole executable `aliases.get(` lives inside the probe.
        Enforces the ban structurally, so a future axis cannot smuggle in a raw one."""
        offenders = []
        for lineno, line in enumerate(inspect.getsource(common).splitlines(), 1):
            code = line.split("#", 1)[0]  # drop trailing comments
            if "aliases.get(" in code:
                offenders.append((lineno, line.strip()))
        probe_src = inspect.getsource(resolve_relation)
        assert [ln for ln in offenders if ln[1] not in probe_src] == [], (
            f"raw `aliases.get(` outside resolve_relation -> {offenders}"
        )
