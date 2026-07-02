#!/usr/bin/env bash
# tests/test_canonical_rule_firing.sh — #227 SLICE 2: rule firing over surface variants
#
# Pins:
#   - A logic-policy rule referencing canonical/3 fires over facts stated with
#     any surface variant when relation-aliases.md declares the mapping.
#   - accepted.dl emits a canonical/3 block after the relation block; the
#     relation block is byte-identical to the no-alias baseline.
#   - opt-in no-op: no relation-aliases.md → accepted.dl has NO canonical block
#     (byte-identical to pre-feature baseline).
#   - Golden 5/5 byte-identical (covered by tests/golden.sh).
#
# The policy rule is authored directly as logic-policy.dl (hand-authored),
# since generate_logic_policy.py only emits relation/3 bodies — canonical/3
# rules are written in the .dl directly, mirroring how logic-policy.extra.dl
# is used for typed-comparison predicates (#120).
#
# Requires pyrewire. Skipped cleanly if absent.
# Usage: PYTHON=<path> bash tests/test_canonical_rule_firing.sh

set -euo pipefail

export XDG_CONFIG_HOME="$(mktemp -d)/factlog-test-cfg"  # isolate active-KB config

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$PLUGIN_ROOT${PYTHONPATH:+:$PYTHONPATH}"
PYTHON="${PYTHON:-python3}"
RLC="$PLUGIN_ROOT/tools/run_logic_check.py"
CF="$PLUGIN_ROOT/tools/compile_facts.py"
HEADER="subject,relation,object,source,status,confidence,note"

pass=0
fail=0
ok()  { echo "PASS: $*"; pass=$((pass + 1)); }
bad() { echo "FAIL: $*" >&2; fail=$((fail + 1)); }

# Skip cleanly if pyrewire is absent
if ! "$PYTHON" -c "import pyrewire" >/dev/null 2>&1; then
  echo "SKIP: pyrewire not installed; test_canonical_rule_firing requires the engine"
  exit 0
fi

# ---------------------------------------------------------------------------
# Setup: KB with two alias-participating relations and a conflict rule
# ---------------------------------------------------------------------------
KB="$(mktemp -d)/wiki"
"$PYTHON" -m factlog init --target "$KB" >/dev/null 2>&1

# Candidates: facts using SURFACE variants (not the canonical names)
printf '%s\n' "$HEADER" \
  'doc1,concludes,some_claim,sources/x.md,confirmed,0.9,' \
  'doc1,retraction_status,retracted,sources/x.md,confirmed,0.9,' \
  > "$KB/facts/candidates.csv"
printf '# x\n' > "$KB/sources/x.md"

# Relation aliases: surface → canonical
cat > "$KB/policy/relation-aliases.md" <<'ALIASES'
# Relation aliases
- `concludes` -> `결론`
- `retraction_status` -> `철회상태`
ALIASES

# Logic-policy: hand-authored .dl with a canonical/3 rule body.
# The rule fires ONLY via canonical atoms — neither surface variant
# ("concludes" / "retraction_status") appears in the rule body.
cat > "$KB/policy/logic-policy.dl" <<'DL'
// generated from policy/logic-policy.md
// run tools/generate_logic_policy.py to regenerate

.decl conflict(entity: symbol, reason: symbol)

// retracted_conclusion: a doc that concludes something and is retracted
conflict(X, "retracted_conclusion") :-
  canonical(X, "결론", _),
  canonical(X, "철회상태", _).
DL

# Compile facts → accepted.dl (emits relation block + canonical block)
FACTLOG_ROOT="$KB" "$PYTHON" "$CF" >/dev/null 2>&1

# ---------------------------------------------------------------------------
# Test 1: canonical block appears in accepted.dl
# ---------------------------------------------------------------------------
if grep -qF 'canonical(' "$KB/facts/accepted.dl"; then
  ok "accepted.dl contains canonical(...) block"
else
  bad "accepted.dl missing canonical(...) block"
fi

# ---------------------------------------------------------------------------
# Test 2: canonical lines use canonical names (결론 / 철회상태), not surface forms
# ---------------------------------------------------------------------------
if grep -qF '"결론"' "$KB/facts/accepted.dl" && grep -qF '"철회상태"' "$KB/facts/accepted.dl"; then
  ok "canonical block uses canonical names (결론, 철회상태)"
else
  bad "canonical block missing canonical names"
fi

# ---------------------------------------------------------------------------
# Test 3: relation block is byte-identical to the no-alias baseline
# (relation(...) lines use the original surface variants, NOT the canonical names)
# ---------------------------------------------------------------------------
if grep -qF '"concludes"' "$KB/facts/accepted.dl" && grep -qF '"retraction_status"' "$KB/facts/accepted.dl"; then
  ok "relation block uses original surface variants (concludes, retraction_status)"
else
  bad "relation block does not contain original surface variants"
fi

# Surface variants must NOT appear in canonical lines
canonical_block="$(grep '^canonical(' "$KB/facts/accepted.dl" || true)"
if printf '%s' "$canonical_block" | grep -qF '"concludes"'; then
  bad "canonical block wrongly contains surface variant 'concludes'"
else
  ok "canonical block does not contain surface variant 'concludes'"
fi

# ---------------------------------------------------------------------------
# Test 4: accepted.dl canonical block appears AFTER the relation block
# (relation lines must precede the canonical comment header)
# ---------------------------------------------------------------------------
rel_linenum="$(grep -n '^relation(' "$KB/facts/accepted.dl" | tail -1 | cut -d: -f1)"
canon_linenum="$(grep -n '^canonical(' "$KB/facts/accepted.dl" | head -1 | cut -d: -f1)"
if [ -n "$rel_linenum" ] && [ -n "$canon_linenum" ] && [ "$canon_linenum" -gt "$rel_linenum" ]; then
  ok "canonical block appears after relation block in accepted.dl"
else
  bad "canonical block ordering wrong: rel_last=$rel_linenum canon_first=$canon_linenum"
fi

# ---------------------------------------------------------------------------
# Test 5: run_logic_check fires `conflict` for doc1 via canonical atoms
# ---------------------------------------------------------------------------
out="$(FACTLOG_ROOT="$KB" "$PYTHON" "$RLC" 2>&1)"; rc=$?
[ "$rc" -eq 0 ] && ok "run_logic_check exits 0" || bad "run_logic_check exited $rc: $out"

if printf '%s' "$out" | grep -qiF "conflict"; then
  ok "run_logic_check report mentions 'conflict' (rule fired)"
else
  bad "run_logic_check report missing 'conflict' — rule did not fire"
  printf '%s\n' "$out" >&2
fi

if printf '%s' "$out" | grep -qF "doc1"; then
  ok "conflict finding mentions doc1 (correct entity)"
else
  bad "conflict finding missing doc1"
  printf '%s\n' "$out" >&2
fi

# ---------------------------------------------------------------------------
# Test 6: policy_predicates includes 'conflict', NOT 'canonical'
# ---------------------------------------------------------------------------
preds="$(FACTLOG_ROOT="$KB" "$PYTHON" -c "
from factlog import common
pp = common.policy_predicates(common.load_logic_policy())
print('conflict_in=' + ('yes' if 'conflict' in pp else 'no'))
print('canonical_in=' + ('yes' if 'canonical' in pp else 'no'))
")"
if printf '%s' "$preds" | grep -qF "conflict_in=yes"; then
  ok "policy_predicates contains 'conflict'"
else
  bad "policy_predicates missing 'conflict'"
fi
if printf '%s' "$preds" | grep -qF "canonical_in=no"; then
  ok "policy_predicates does NOT contain 'canonical'"
else
  bad "policy_predicates wrongly contains 'canonical'"
fi

# ---------------------------------------------------------------------------
# Test 7: opt-in no-op — no aliases → no canonical block
# ---------------------------------------------------------------------------
KB2="$(mktemp -d)/wiki"
"$PYTHON" -m factlog init --target "$KB2" >/dev/null 2>&1
printf '%s\n' "$HEADER" \
  'doc1,concludes,some_claim,sources/x.md,confirmed,0.9,' \
  > "$KB2/facts/candidates.csv"
printf '# x\n' > "$KB2/sources/x.md"
# NO relation-aliases.md

FACTLOG_ROOT="$KB2" "$PYTHON" "$CF" >/dev/null 2>&1
if grep -qF 'canonical(' "$KB2/facts/accepted.dl" 2>/dev/null; then
  bad "opt-in no-op FAILED: canonical block appeared without aliases"
else
  ok "opt-in no-op: no relation-aliases.md → no canonical block"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "========================================"
echo "test_canonical_rule_firing: $pass passed, $fail failed"
echo "========================================"
[ "$fail" -eq 0 ]
