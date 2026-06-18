#!/usr/bin/env bash
# tests/test_review.sh — human-review CLI: review / accept / reject (#85)
#
# Pins (XDG-isolated; synthetic data):
#   - review lists only pending facts (candidate/needs_review), grouped, with note
#   - review --status narrows to one pending status; empty queue is graceful
#   - accept promotes matching pending row(s) -> accepted (into accepted.dl)
#   - reject retires matching pending row(s) -> superseded (out of accepted.dl)
#   - a non-pending (confirmed/accepted/superseded) match is skipped -> rc 1
#   - partial/wildcard terms; --dry-run no-op; no-match rc 1; no/extra term rc 2
#
# Usage: bash tests/test_review.sh

set -euo pipefail

export XDG_CONFIG_HOME="$(mktemp -d)/factlog-test-cfg"  # isolate active-KB config (#62)

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$PLUGIN_ROOT${PYTHONPATH:+:$PYTHONPATH}"
PYTHON="${PYTHON:-python3}"
H="subject,relation,object,source,status,confidence,note"

pass=0
fail=0
ok() { echo "PASS: $*"; pass=$((pass + 1)); }
bad() { echo "FAIL: $*" >&2; fail=$((fail + 1)); }

seed() {  # $1 = KB
  local kb="$1"
  "$PYTHON" -m factlog init --target "$kb" >/dev/null
  printf 'a\n' > "$kb/sources/a.md"
  printf '%s\n%s\n%s\n%s\n' "$H" \
    'X,rel,Y,sources/a.md,candidate,0.8,maybe' \
    'X,rel,Z,sources/a.md,needs_review,0.5,unsure' \
    'W,rel,V,sources/a.md,confirmed,0.9,already engine input' > "$kb/facts/candidates.csv"
}

# --- review lists pending only (not the confirmed row) ------------------------
KB="$(mktemp -d)/wiki"; seed "$KB"
out="$("$PYTHON" -m factlog review --target "$KB" 2>&1)"
printf '%s\n' "$out"; echo "---"
printf '%s' "$out" | grep -qF "2 pending fact(s)" && ok "review counts both pending facts" || bad "pending count wrong"
printf '%s' "$out" | grep -qF "X / rel / Y" && printf '%s' "$out" | grep -qF "X / rel / Z" && ok "review lists candidate + needs_review" || bad "pending facts missing"
printf '%s' "$out" | grep -qF "W / rel / V" && bad "review listed a confirmed fact" || ok "review omits the confirmed fact"
printf '%s' "$out" | grep -qF "note: maybe" && ok "review shows the note" || bad "note missing"

# --- review --status narrows -------------------------------------------------
out="$("$PYTHON" -m factlog review --status candidate --target "$KB" 2>&1)"
printf '%s' "$out" | grep -qF "X / rel / Y" && ! printf '%s' "$out" | grep -qF "X / rel / Z" \
  && ok "review --status candidate shows only candidate rows" || bad "--status filter wrong"

# --- accept --dry-run changes nothing ----------------------------------------
before="$(cat "$KB/facts/candidates.csv")"
"$PYTHON" -m factlog accept X rel Y --dry-run --target "$KB" >/dev/null 2>&1
[ "$(cat "$KB/facts/candidates.csv")" = "$before" ] && ok "accept --dry-run leaves candidates.csv unchanged" || bad "--dry-run mutated state"

# --- accept promotes a pending fact to engine input --------------------------
"$PYTHON" -m factlog accept X rel Y --target "$KB" >/dev/null 2>&1
grep -q "X,rel,Y,sources/a.md,accepted," "$KB/facts/candidates.csv" && ok "accept sets status -> accepted" || bad "accept did not set accepted"
grep -q '"X", "rel", "Y"' "$KB/facts/accepted.dl" && ok "accepted fact compiled into accepted.dl" || bad "accept did not recompile accepted.dl"

# --- reject retires a pending fact -------------------------------------------
"$PYTHON" -m factlog reject X rel Z --target "$KB" >/dev/null 2>&1
grep -q "X,rel,Z,sources/a.md,superseded," "$KB/facts/candidates.csv" && ok "reject sets status -> superseded" || bad "reject did not supersede"
grep -q '"X", "rel", "Z"' "$KB/facts/accepted.dl" && bad "rejected fact leaked into accepted.dl" || ok "rejected fact stays out of accepted.dl"

# --- a non-pending match is skipped (rc 1), not silently flipped --------------
KB="$(mktemp -d)/wiki"; seed "$KB"
set +e; out="$("$PYTHON" -m factlog accept W rel V --target "$KB" 2>&1)"; rc=$?; set -e
[ "$rc" -eq 1 ] && printf '%s' "$out" | grep -qF "not pending" && ok "accept on a confirmed fact is skipped (rc 1)" || bad "non-pending accept not handled (rc=$rc)"
grep -q "W,rel,V,sources/a.md,confirmed," "$KB/facts/candidates.csv" && ok "the confirmed row is left untouched" || bad "confirmed row was altered"

# --- partial/wildcard: accept all pending for subject X ----------------------
KB="$(mktemp -d)/wiki"; seed "$KB"
"$PYTHON" -m factlog accept X --target "$KB" >/dev/null 2>&1
[ "$(grep -c ",accepted," "$KB/facts/candidates.csv")" -eq 2 ] && ok "subject-only accept promotes all pending for X" || bad "partial accept count wrong"

# --- error paths -------------------------------------------------------------
set +e
"$PYTHON" -m factlog accept nope nope nope --target "$KB" >/dev/null 2>&1; [ $? -eq 1 ] && ok "no-match accept rc 1" || bad "no-match rc wrong"
"$PYTHON" -m factlog accept - - - --target "$KB" >/dev/null 2>&1; [ $? -eq 2 ] && ok "all-wildcard accept rc 2" || bad "all-wildcard rc wrong"
"$PYTHON" -m factlog accept a b c d --target "$KB" >/dev/null 2>&1; [ $? -eq 2 ] && ok ">3 terms accept rc 2" || bad ">3 terms rc wrong"
"$PYTHON" -m factlog review --target "$(mktemp -d)" >/dev/null 2>&1; [ $? -ne 0 ] && ok "review on a non-KB path errors" || bad "non-KB review should error"
set -e

# --- recompile failure: status saved, rc 1, clear message --------------------
KB="$(mktemp -d)/wiki"; seed "$KB"
rm -f "$KB/facts/accepted.dl"; mkdir "$KB/facts/accepted.dl"   # make compile_facts fail to write
set +e; out="$("$PYTHON" -m factlog accept X rel Y --target "$KB" 2>&1)"; rc=$?; set -e
[ "$rc" -eq 1 ] && printf '%s' "$out" | grep -qF "NOT recompiled" && ok "recompile failure exits rc 1 with 'NOT recompiled'" || bad "compile-failure path wrong (rc=$rc)"
grep -q "X,rel,Y,sources/a.md,accepted," "$KB/facts/candidates.csv" && ok "status change saved even when recompile fails" || bad "status not saved on recompile failure"
rmdir "$KB/facts/accepted.dl"

# --- empty queue is graceful -------------------------------------------------
KB="$(mktemp -d)/wiki"
"$PYTHON" -m factlog init --target "$KB" >/dev/null
printf '%s\n%s\n' "$H" 'A,rel,B,sources/a.md,confirmed,0.9,' > "$KB/facts/candidates.csv"
"$PYTHON" -m factlog review --target "$KB" 2>&1 | grep -qF "no pending facts" && ok "empty pending queue is graceful" || bad "empty queue not handled"

echo ""
echo "========================================"
echo "test_review: $pass passed, $fail failed"
echo "========================================"
[ "$fail" -eq 0 ]
