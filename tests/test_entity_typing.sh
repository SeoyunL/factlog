#!/usr/bin/env bash
# tests/test_entity_typing.sh — entity vs literal typing (#50)
#
# Pins:
#   - no policy/attribute-relations.md  -> entity_set == value_set (backward compat)
#   - declaring a relation attribute    -> its object leaves entity_set but stays
#     in value_set (literal still a verifiable query object)
#   - classify_query: a relation query whose OBJECT is a declared literal is
#     QUERY_OK; a path query NAMING that literal is rejected (literals aren't
#     path nodes); subject/count still validated against entity_set
#   - factlog init scaffolds policy/attribute-relations.md
#
# Deterministic; no pyrewire.  Usage: bash tests/test_entity_typing.sh

set -euo pipefail

export XDG_CONFIG_HOME="$(mktemp -d)/factlog-test-cfg"  # isolate active-KB config (#62) from the dev machine

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$PLUGIN_ROOT${PYTHONPATH:+:$PYTHONPATH}"
PYTHON="${PYTHON:-python3}"

pass=0
fail=0
ok() { echo "PASS: $*"; pass=$((pass + 1)); }
bad() { echo "FAIL: $*" >&2; fail=$((fail + 1)); }

KB="$(mktemp -d)/wiki"
"$PYTHON" -m factlog init --target "$KB" >/dev/null
H="subject,relation,object,source,status,confidence,note"
printf '%s\n%s\n%s\n' "$H" \
  '을서비스,정식_운영,2030.1,sources/a.md,accepted,0.9,' \
  '갑봇,통합_대상,을서비스,sources/a.md,accepted,0.9,' > "$KB/facts/candidates.csv"
printf 'x\n' > "$KB/sources/a.md"

# --- scaffold -----------------------------------------------------------------
[ -f "$KB/policy/attribute-relations.md" ] && ok "init scaffolds policy/attribute-relations.md" || bad "attribute-relations.md not scaffolded"

run_py() { FACTLOG_ROOT="$KB" "$PYTHON" - "$@"; }

# --- backward compat: scaffolded stub declares nothing (examples are comments) -
# so entity_set == value_set and the literal is (still) an entity.
verdict="$(run_py <<'PY'
import os, sys; sys.path.insert(0, "tools")
import common as c
facts = c.load_facts()
print("attr stub empty:", c.attribute_relations() == set())
es, vs = c.entity_set(facts), c.value_set(facts)
print("OK" if (c.attribute_relations() == set() and "2030.1" in es and es == vs)
      else f"FAIL es={sorted(es)} vs={sorted(vs)} attr={c.attribute_relations()}")
PY
)"
echo "$verdict" | grep -q "^OK$" && ok "scaffolded stub declares nothing -> entity_set == value_set (backward compat)" || bad "$verdict"

# --- declare 정식_운영 attribute ----------------------------------------------
printf -- '- `정식_운영`\n' > "$KB/policy/attribute-relations.md"
verdict="$(run_py <<'PY'
import sys; sys.path.insert(0, "tools")
import common as c
facts = c.load_facts()
es, vs = c.entity_set(facts), c.value_set(facts)
checks = {
    "literal out of entity_set": "2030.1" not in es,
    "literal still in value_set": "2030.1" in vs,
    "entity object retained": "을서비스" in es,
    "subject retained": "갑봇" in es,
}
bad = [k for k, v in checks.items() if not v]
print("OK" if not bad else "FAIL: " + ", ".join(bad))
PY
)"
[ "$verdict" = "OK" ] && ok "declared attribute relation excludes its literal object from entity_set only" || bad "$verdict"

# --- classify_query routing with the literal ----------------------------------
verdict="$(run_py <<'PY'
import sys; sys.path.insert(0, "tools")
import common as c
facts = c.load_facts(); P = ""  # empty policy program: no logic-policy.dl needed
cases = {
    "relation w/ literal object -> ok":
        c.classify_query('relation("을서비스","정식_운영","2030.1")?', facts, P)[1] == c.QUERY_OK,
    "relation w/ entity object -> ok":
        c.classify_query('relation("갑봇","통합_대상","을서비스")?', facts, P)[1] == c.QUERY_OK,
    "path naming literal -> rejected":
        c.classify_query('path("을서비스","2030.1")?', facts, P)[1] == c.QUERY_ENTITY_NOT_ACCEPTED,
    "relation w/ unknown object -> rejected":
        c.classify_query('relation("을서비스","정식_운영","9999.9")?', facts, P)[1] == c.QUERY_ENTITY_NOT_ACCEPTED,
}
bad = [k for k, v in cases.items() if not v]
print("OK" if not bad else "FAIL: " + " | ".join(bad))
PY
)"
[ "$verdict" = "OK" ] && ok "classify: literal object queryable; literal rejected as path node / unknown value" || bad "$verdict"

echo ""
echo "========================================"
echo "test_entity_typing: $pass passed, $fail failed"
echo "========================================"
[ "$fail" -eq 0 ]
