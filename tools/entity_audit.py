#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Entity audit: surface entity fragmentation and literal-as-entity smells.

As a KB grows across sources, the same real-world thing can fragment into
several surface forms ('갑봇' / 'Samplebot'), and literal values (dates, numbers)
can leak in as entities. A plain notes wiki cannot see either. This reports,
deterministically and informationally (always exit 0):

  1. Entities — distinct engine-fact entities, each with its fact count and the
     statuses it appears under. Declared literals (objects of attribute
     relations, see policy/attribute-relations.md) are listed separately.
  2. Fragmentation — pairs of ENTITIES that may be the same thing: normalized-
     equal (spacing/punctuation/case only), substring-contained, or sharing a
     significant token. A heuristic — expect false positives; it surfaces
     candidates for human judgement, it does not merge anything.
  3. Literal suspects — objects that look like a literal (date / number /
     ordinal) under a relation NOT yet declared in attribute-relations.md;
     suggests declaring that relation (pairs with entity-vs-literal typing).

A typed literal written as a COMPOUND TERM (`date(2020)`, `number(19)`) is a
literal by syntax alone, whatever the relation says, so it never counts as an
entity here — see `_is_compound_term`.

Usage:
    python3 entity_audit.py [--wiki <kb>]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

_TOOLS_DIR = Path(__file__).parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))


# Resolve the KB root and export it before importing common, which binds
# its module-level paths from FACTLOG_ROOT at import time.
import factlog_config  # noqa: E402

os.environ["FACTLOG_ROOT"] = factlog_config.resolve_root_from_argv("--wiki")

from common import (  # noqa: E402
    CANDIDATES_CSV,
    attribute_relation_forms,
    is_attribute_relation,
    engine_facts,
    ensure_dirs,
    entity_set,
    load_facts,
)
from factlog import literal_types  # noqa: E402

# Heuristic: looks like a literal VALUE rather than a first-class entity. Covers
# dates (2030.1 / 2024-07-01), plain/comma/decimal numbers (2026, 1,000, 3.14),
# and number+unit forms incl. an optional trailing word (1호, 1호 항목, 2026년,
# 100억, 제3호). Advisory only — a human confirms before declaring the relation;
# a few false positives (e.g. a named concept like '4차 산업혁명') are acceptable
# in exchange for not missing the motivating value forms.
_LITERAL_RE = re.compile(
    r"^\d{4}[.\-/]\d{1,2}([.\-/]\d{1,2})?$"                       # date
    r"|^\d[\d,]*(\.\d+)?$"                                        # number / comma / decimal
    r"|^제?\d+\s*(호|차|위|개|번|년|월|일|억|만|천|원|%)(\s+.+)?$"   # number + unit (+word)
)


# A typed literal written the way text-to-fact.md mandates: `date(2020)`,
# `number(19)`, `ordinal(3)`, `amount(100,"억")`. The wrapper names come from
# literal_types.TYPES — the single source of the notation — so this file never
# holds a second copy of the list to drift from.
_COMPOUND_TERM_RE = re.compile(
    r"^(?:" + "|".join(sorted(re.escape(t) for t in literal_types.TYPES)) + r")\(.*\)$",
    re.IGNORECASE | re.DOTALL,
)


def _is_compound_term(value: str) -> bool:
    """Is *value* a typed literal in compound-term form?

    Syntax settles it: nothing but a literal is spelled `date(...)`. So this does
    NOT consult attribute-relations.md. It cannot, and must not wait for it — a KB
    that follows the mandated notation but has not declared the relation yet was
    leaking every such value into the entity set, where `_tokens` split the wrapper
    off and made `date` a token shared by every date. All C(n,2) date pairs then
    surfaced as fragmentation candidates and buried the real ones (#386).
    """
    return bool(_COMPOUND_TERM_RE.match(value.strip()))


def _looks_literal(value: str) -> bool:
    """Literal by the prose heuristic OR by compound-term syntax."""
    return _is_compound_term(value) or bool(_LITERAL_RE.match(value))


def _norm(s: str) -> str:
    return re.sub(r"[\s·_\-/().,]+", "", s).lower()


def _tokens(s: str) -> set[str]:
    return {t for t in re.split(r"[\s·_\-/().,]+", s) if len(t) >= 2}


def audit(facts: list[dict[str, str]]) -> dict[str, object]:
    rows = engine_facts(facts)
    # Surface forms via the shared predicate: comparing raw declarations made this
    # advise declaring a relation that WAS already declared, just under its alias.
    literal_rels = attribute_relation_forms()
    # Excludes declared-literal objects; compound terms go too, since their form
    # already proves they are values and pairing them is pure noise (#386).
    entities = {e for e in entity_set(facts) if not _is_compound_term(e)}

    fact_count: Counter[str] = Counter()
    statuses: dict[str, set[str]] = defaultdict(set)
    declared_literals: set[str] = set()
    literal_suspects: dict[str, set[str]] = defaultdict(set)  # relation -> {objects}

    for row in rows:
        s, rel, o, st = row["subject"], row["relation"], row["object"], row["status"]
        for ent in (s, o):
            if ent:
                fact_count[ent] += 1
                statuses[ent].add(st)
        if o and is_attribute_relation(rel, literal_rels):
            declared_literals.add(o)
        elif o and _looks_literal(o):
            literal_suspects[rel].add(o)

    # Fragmentation clusters among entities only. Precompute norm/tokens once per
    # entity (the pairing is O(n^2); don't re-normalise inside the inner loop).
    ents = sorted(entities)
    norm = {e: _norm(e) for e in ents}
    toks = {e: _tokens(e) for e in ents}
    clusters: list[tuple[str, str, str]] = []
    for i, a in enumerate(ents):
        for b in ents[i + 1:]:
            na, nb = norm[a], norm[b]
            shared = toks[a] & toks[b]
            if na == nb:
                clusters.append((a, b, "normalized-equal (spacing/punct/case only)"))
            elif na and (na in nb or nb in na):
                clusters.append((a, b, "substring-contained"))
            elif shared:
                clusters.append((a, b, f"shared token {sorted(shared)}"))

    return {
        "entities": sorted(entities),
        "declared_literals": sorted(declared_literals),
        "fact_count": fact_count,
        "statuses": statuses,
        "clusters": clusters,
        "literal_suspects": literal_suspects,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit entities for fragmentation / literal leakage.")
    parser.add_argument("--wiki", default=os.environ.get("FACTLOG_ROOT", "."), help="KB root")
    parser.parse_args(argv)

    ensure_dirs()
    facts = load_facts() if CANDIDATES_CSV.is_file() else []
    if not facts:
        print("entity_audit: no candidate facts")
        return 0

    a = audit(facts)
    ents = a["entities"]
    fc, st = a["fact_count"], a["statuses"]
    print(
        f"entity_audit: {len(ents)} entit(y/ies), {len(a['declared_literals'])} declared literal(s), "
        f"{len(a['clusters'])} fragmentation candidate(s), "
        f"{sum(len(v) for v in a['literal_suspects'].values())} literal suspect(s)"
    )

    print("\nentities (fact count, statuses):")
    for e in ents:
        print(f"  [{fc[e]:>2}] {e}  ({'/'.join(sorted(st[e]))})")
    if a["declared_literals"]:
        print("\ndeclared literals (attribute-relation objects, not entities):")
        for v in a["declared_literals"]:
            print(f"  [{fc[v]:>2}] {v}  ({'/'.join(sorted(st[v]))})")

    if a["clusters"]:
        print("\nfragmentation candidates (HEURISTIC — expect false positives; human judgement):", file=sys.stderr)
        for x, y, why in a["clusters"]:
            print(f"  • '{x}' ⟷ '{y}' — {why}", file=sys.stderr)

    if a["literal_suspects"]:
        print("\nliteral suspects (object looks literal under an undeclared relation):", file=sys.stderr)
        for rel in sorted(a["literal_suspects"]):
            vals = ", ".join(sorted(a["literal_suspects"][rel]))
            print(f"  • relation '{rel}' has literal-looking object(s): {vals}", file=sys.stderr)
            print(f"      → consider adding '{rel}' to policy/attribute-relations.md", file=sys.stderr)

    return 0


if __name__ == "__main__":
    from common import run_cli

    sys.exit(run_cli(main))
