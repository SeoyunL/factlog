#!/usr/bin/env bash
# tests/test_conflicts.sh — single-valued contradiction detection + supersession (#30)
#
# Pins:
#   - a single-valued relation with 2 distinct objects for one subject = conflict
#   - marking the outdated row status='superseded' resolves it (non-destructive)
#   - a multi-valued (undeclared) relation with 2 objects is NOT a conflict
#   - no policy/single-valued.md => nothing to check (exit 0)
#   - 'superseded' rows survive merge and are excluded from accepted.dl
#   - validate.py accepts the 'superseded' status
#
# Deterministic; no pyrewire required.  Usage: bash tests/test_conflicts.sh

set -euo pipefail

export XDG_CONFIG_HOME="$(mktemp -d)/factlog-test-cfg"  # isolate active-KB config (#62) from the dev machine

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$PLUGIN_ROOT${PYTHONPATH:+:$PYTHONPATH}"
PYTHON="${PYTHON:-python3}"
HEADER="subject,relation,object,source,status,confidence,note"

pass=0
fail=0
ok() { echo "PASS: $*"; pass=$((pass + 1)); }
bad() { echo "FAIL: $*" >&2; fail=$((fail + 1)); }

KB="$(mktemp -d)/wiki"
"$PYTHON" -m factlog init --target "$KB" >/dev/null
CONFLICTS="$PLUGIN_ROOT/tools/check_conflicts.py"
csv() { printf '%s\n' "$HEADER" "$@" > "$KB/facts/candidates.csv"; }
run_conflicts() { "$PYTHON" "$CONFLICTS" --wiki "$KB" >/dev/null 2>&1; }

# no single-valued.md yet -> nothing to check
if run_conflicts; then ok "no single-valued.md => exit 0 (nothing to check)"; else bad "should be 0 without single-valued.md"; fi

# declare 주_속성 single-valued
printf '# single-valued relations\n\n- 주_속성\n' > "$KB/policy/single-valued.md"

# multi-valued (undeclared) relation with 2 objects -> NOT a conflict
csv '갑봇,구성_요소,ToolA,sources/x.md,confirmed,0.9,' '갑봇,구성_요소,을서비스,sources/x.md,confirmed,0.9,'
printf '# x\n' > "$KB/sources/x.md"
if run_conflicts; then ok "multi-valued relation with 2 objects is not flagged"; else bad "multi-valued wrongly flagged"; fi

# single-valued relation with 2 distinct objects -> CONFLICT
csv '을서비스,주_속성,값가,sources/x.md,confirmed,0.9,' '을서비스,주_속성,값나,sources/x.md,confirmed,0.9,'
if run_conflicts; then bad "single-valued conflict NOT detected"; else ok "single-valued conflict detected (exit non-zero)"; fi
cout="$("$PYTHON" "$CONFLICTS" --wiki "$KB" 2>&1 || true)"
if printf '%s' "$cout" | grep -qF "CONFLICT"; then ok "conflict reported with CONFLICT line"; else bad "no CONFLICT line"; fi

# resolve by superseding the outdated row -> conflict clears (non-destructively)
csv '을서비스,주_속성,값가,sources/x.md,superseded,0.9,old' '을서비스,주_속성,값나,sources/x.md,confirmed,0.9,current'
if run_conflicts; then ok "superseding the outdated row resolves the conflict"; else bad "superseded row still conflicts"; fi

# superseded survives merge and is excluded from accepted.dl
printf '[{"subject":"을서비스","relation":"주_속성","object":"값가","source":"sources/x.md","status":"superseded","confidence":0.9,"note":"old"},{"subject":"을서비스","relation":"주_속성","object":"값나","source":"sources/x.md","status":"confirmed","confidence":0.9,"note":"current"}]' > "$KB/runs/r.json"
"$PYTHON" "$PLUGIN_ROOT/tools/merge_candidates.py" --wiki "$KB" >/dev/null 2>&1 || true
if grep -q ',superseded,' "$KB/facts/candidates.csv"; then ok "merge preserves superseded status"; else bad "merge dropped/renamed superseded status"; fi
FACTLOG_ROOT="$KB" "$PYTHON" "$PLUGIN_ROOT/tools/compile_facts.py" >/dev/null 2>&1
if grep -q '"값가"' "$KB/facts/accepted.dl"; then bad "superseded fact leaked into accepted.dl"; else ok "superseded fact excluded from accepted.dl"; fi
if grep -q '"값나"' "$KB/facts/accepted.dl"; then ok "current fact compiled to accepted.dl"; else bad "current fact missing from accepted.dl"; fi

# H1: a human-marked superseded row is PRESERVED across a re-merge even when the
# originating run JSON re-asserts it as confirmed (resolution is durable).
csv '을서비스,주_속성,값가,sources/x.md,superseded,0.9,old' '을서비스,주_속성,값나,sources/x.md,confirmed,0.9,current'
printf '[{"subject":"을서비스","relation":"주_속성","object":"값가","source":"sources/x.md","status":"confirmed","confidence":0.9,"note":"re-asserted"}]' > "$KB/runs/r.json"
"$PYTHON" "$PLUGIN_ROOT/tools/merge_candidates.py" --wiki "$KB" >/dev/null 2>&1 || true
if grep -q '을서비스,주_속성,값가,.*,superseded,' "$KB/facts/candidates.csv"; then ok "re-merge preserves human-marked superseded (durable resolution)"; else bad "re-merge reverted the superseded row"; fi
if run_conflicts; then ok "conflict stays resolved after re-merge"; else bad "conflict reappeared after re-merge"; fi
rm -f "$KB/runs/r.json"

# M1: single-valued name parses from a backtick token with a trailing description
printf '# single-valued\n\n- `주_속성` (the base LLM)\n' > "$KB/policy/single-valued.md"
got="$("$PYTHON" -c "import sys; sys.path.insert(0,'$PLUGIN_ROOT/tools'); import os; os.environ['FACTLOG_ROOT']='$KB'; import common; print('주_속성' in common.single_valued_relations())")"
[ "$got" = "True" ] && ok "single-valued name parsed from backtick+description line" || bad "backtick+description line mis-parsed (false negative)"
printf '# single-valued\n\n- 주_속성\n' > "$KB/policy/single-valued.md"

# validate.py accepts the superseded status (no invalid-status error)
if "$PYTHON" "$PLUGIN_ROOT/tools/validate.py" "$KB" 2>&1 | grep -q "invalid status"; then bad "validate rejected superseded status"; else ok "validate accepts superseded status"; fi

echo ""
echo "========================================"
echo "test_conflicts: $pass passed, $fail failed"
echo "========================================"
[ "$fail" -eq 0 ]
