#!/usr/bin/env bash
# tests/smoke.sh — clean-environment plugin smoke harness (AC5)
#
# Validates the 4 deterministic steps of the factlog pipeline in a fresh
# virtualenv with a freshly-initialised KB seeded from examples/sample-kb.
#
# Design notes:
#   - FACTLOG_ROOT is exported so tools/ scripts resolve the KB without
#     relying on cwd.  This matches the fix in u1 where ensure_wiki_root
#     no longer requires a tools/ directory alongside the KB.
#   - Only deterministic outputs are asserted here:
#       facts/accepted.dl       — from compile_facts.py
#       facts/logic_report.txt  — from run_logic_check.py
#     The full facts/query.dl and decisions/correction_trace.md are produced by
#     the LLM (Claude in-session) steps. Step 7 stands in for the /factlog query
#     step with a minimal hand-written query.dl so the question→query→evaluation
#     path (AC3) is exercised end-to-end against the deterministic engine; the
#     smoke still does not depend on a live Claude session.
#   - Local marketplace path is used for plugin references; no remote
#     operations.  See .claude-plugin/marketplace.json for the install path.
#
# Usage:
#   bash tests/smoke.sh
#
# Returns 0 if all checks pass, 1 on first failure.
#
# Acceptance checks (from unit u12):
#   bash -n tests/smoke.sh                        (syntax check)
#   CD /tmp; factlog init + run_logic_check.py    (FACTLOG_ROOT export check)
#   grep counts remote-push lines — must be zero  (no remote ops)

set -euo pipefail

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SAMPLE_KB="$PLUGIN_ROOT/examples/sample-kb"

SMOKE_VENV="/tmp/factlog-smoke-venv"
SMOKE_KB="/tmp/factlog-smoke-kb"
PYTHON="$SMOKE_VENV/bin/python"

pass=0
fail=0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
ok() {
  echo "PASS: $*"
  pass=$((pass + 1))
}

fail_msg() {
  echo "FAIL: $*" >&2
  fail=$((fail + 1))
}

assert_nonempty() {
  local path="$1"
  local label="${2:-$1}"
  if [ -s "$path" ]; then
    ok "$label exists and is non-empty"
  else
    fail_msg "$label missing or empty (expected at $path)"
  fi
}

assert_exit0() {
  local label="$1"
  shift
  if "$@"; then
    ok "$label exit 0"
  else
    fail_msg "$label exited non-zero"
  fi
}

assert_grep() {
  local pattern="$1"
  local path="$2"
  local label="${3:-grep '$pattern' in $path}"
  if grep -qE "$pattern" "$path"; then
    ok "$label"
  else
    fail_msg "$label (pattern '$pattern' not found in $path)"
  fi
}

# ---------------------------------------------------------------------------
# Step 1: fresh virtualenv + pip install
# ---------------------------------------------------------------------------
echo "=== Step 1: create venv + install requirements ==="
rm -rf "$SMOKE_VENV"
python3 -m venv "$SMOKE_VENV"
"$SMOKE_VENV/bin/pip" install --quiet -r "$PLUGIN_ROOT/requirements.txt"
ok "pip install -r requirements.txt"

# Install factlog package itself so 'python -m factlog' works from anywhere.
"$SMOKE_VENV/bin/pip" install --quiet -e "$PLUGIN_ROOT"
ok "pip install -e factlog"

# ---------------------------------------------------------------------------
# Step 2: factlog doctor
# ---------------------------------------------------------------------------
echo ""
echo "=== Step 2: factlog doctor ==="
assert_exit0 "factlog doctor" "$PYTHON" -m factlog doctor

# ---------------------------------------------------------------------------
# Step 3: init fresh KB, seed from sample-kb
# ---------------------------------------------------------------------------
echo ""
echo "=== Step 3: init KB + seed from sample-kb ==="
rm -rf "$SMOKE_KB"
"$PYTHON" -m factlog init --target "$SMOKE_KB"
ok "factlog init --target $SMOKE_KB"

# Seed deterministic content from sample-kb (candidates, sources, pages,
# policy rules, decisions open-questions).  This gives compile_facts.py
# real input and validate.py all required artefacts.
cp "$SAMPLE_KB/facts/candidates.csv" "$SMOKE_KB/facts/"
cp -r "$SAMPLE_KB/sources/." "$SMOKE_KB/sources/"
cp -r "$SAMPLE_KB/pages/." "$SMOKE_KB/pages/"
cp "$SAMPLE_KB/policy/logic-policy.dl" "$SMOKE_KB/policy/"
cp "$SAMPLE_KB/policy/logic-policy.md" "$SMOKE_KB/policy/"
cp "$SAMPLE_KB/decisions/open-questions.md" "$SMOKE_KB/decisions/"
ok "seeded KB from sample-kb"

# ---------------------------------------------------------------------------
# Step 4: compile_facts.py  →  facts/accepted.dl
# ---------------------------------------------------------------------------
echo ""
echo "=== Step 4: compile_facts.py ==="
export FACTLOG_ROOT="$SMOKE_KB"
assert_exit0 "compile_facts.py" \
  "$PYTHON" "$PLUGIN_ROOT/tools/compile_facts.py"
assert_nonempty "$SMOKE_KB/facts/accepted.dl" "facts/accepted.dl"

# ---------------------------------------------------------------------------
# Step 5: run_logic_check.py  →  facts/logic_report.txt
# ---------------------------------------------------------------------------
echo ""
echo "=== Step 5: run_logic_check.py ==="
assert_exit0 "run_logic_check.py" \
  "$PYTHON" "$PLUGIN_ROOT/tools/run_logic_check.py"
assert_nonempty "$SMOKE_KB/facts/logic_report.txt" "facts/logic_report.txt"

# ---------------------------------------------------------------------------
# Step 6: validate.py
# ---------------------------------------------------------------------------
echo ""
echo "=== Step 6: validate.py ==="
assert_exit0 "validate.py" \
  "$PYTHON" "$PLUGIN_ROOT/tools/validate.py" "$SMOKE_KB"

# ---------------------------------------------------------------------------
# Step 7: question→query→evaluation path (AC3 end-to-end)
# ---------------------------------------------------------------------------
# The LLM `/factlog query` step normally writes facts/query.dl. Here we stand
# in for it with a small, schema-valid query.dl (one query that resolves
# against the seeded accepted facts) so the deterministic check→evaluation flow
# is exercised end-to-end and the report's "Query evaluation" section is
# populated with a resolved row — rather than the "no facts/query.dl found"
# placeholder. The seeded triple ("Claude Code", "developed_by", "Anthropic")
# is present in the sample-kb-derived accepted.dl, so it resolves to >=1 row.
echo ""
echo "=== Step 7: query.dl → populated Query evaluation (AC3) ==="
cat > "$SMOKE_KB/facts/query.dl" <<'QUERY_DL'
// smoke: stand-in for the LLM /factlog query step (one resolved query)
relation("Claude Code", "developed_by", "Anthropic")?
QUERY_DL
ok "wrote stand-in facts/query.dl"

assert_exit0 "run_logic_check.py (with query.dl)" \
  "$PYTHON" "$PLUGIN_ROOT/tools/run_logic_check.py"

# The report must now contain a resolved query row, not the empty placeholder.
assert_grep '^- relation results: [1-9][0-9]* rows' \
  "$SMOKE_KB/facts/logic_report.txt" \
  "Query evaluation populated with a resolved (>=1 row) result"
if grep -qF "no facts/query.dl found" "$SMOKE_KB/facts/logic_report.txt"; then
  fail_msg "Query evaluation still shows the empty 'no facts/query.dl found' placeholder"
else
  ok "Query evaluation no longer shows the empty placeholder"
fi

# ---------------------------------------------------------------------------
# Note on remaining LLM-step outputs
# ---------------------------------------------------------------------------
# The full facts/query.dl (translated from policy/questions.md) and
# decisions/correction_trace.md are produced by the Claude in-session LLM steps
# (/factlog query and /factlog repair respectively). Step 7 stands in for
# /factlog query with a minimal hand-written draft so the deterministic
# check→evaluation path is covered here; full question→query translation
# fidelity still requires a live /factlog invocation. AC5 covers the
# deterministic engine.

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "========================================"
echo "Smoke results: $pass passed, $fail failed"
echo "========================================"
if [ "$fail" -gt 0 ]; then
  exit 1
fi
exit 0
