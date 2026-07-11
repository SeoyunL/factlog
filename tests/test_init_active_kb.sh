#!/usr/bin/env bash
# tests/test_init_active_kb.sh — init must not hijack the active KB (#210)
#
# `factlog init` used to write the active-KB config unconditionally. Scaffolding a
# scratch KB anywhere — another shell, a test harness, an agent — therefore
# retargeted the user's accept/reject/amend/sync at it, silently. The failure
# observed in a real KB was every `accept` returning "no fact matches" because the
# commands were pointed at someone else's scratch KB.
#
# Pins:
#   (a) first init (no active KB configured) adopts the target — the first-run
#       convenience is kept
#   (b) a SECOND init elsewhere leaves the active KB alone and says so
#   (c) the KB is still scaffolded either way (init's actual job)
#   (d) re-init of the ALREADY-active KB is a no-op, not a "left unchanged" notice
#   (e) `factlog use` still switches deliberately
#   (f) `setup` adopts the target (that is its job) but ANNOUNCES the replacement
#
# Usage: bash tests/test_init_active_kb.sh

set -euo pipefail

# pwd -P: the CLI resolve()s paths, and on macOS mktemp hands back /var/... while
# resolve() yields /private/var/... — compare like with like.
TMP_ROOT="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$TMP_ROOT"' EXIT

export XDG_CONFIG_HOME="$TMP_ROOT/cfg"  # isolate the active-KB config (#62) from the dev machine

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$PLUGIN_ROOT${PYTHONPATH:+:$PYTHONPATH}"
PYTHON="${PYTHON:-python3}"

pass=0
fail=0
ok() { echo "PASS: $*"; pass=$((pass + 1)); }
bad() { echo "FAIL: $*" >&2; fail=$((fail + 1)); }

MINE="$TMP_ROOT/my-kb"
SCRATCH="$TMP_ROOT/scratch-kb"

active() { "$PYTHON" -m factlog where | sed -n '1s/^active KB: //p'; }

# ------------------------------------------------------------------------ (a)
"$PYTHON" -m factlog init --target "$MINE" >/dev/null
if [ "$(active)" = "$MINE" ]; then
  ok "(a) first init adopts the target as the active KB"
else
  bad "(a) first init did not set the active KB (got '$(active)')"
fi

# ------------------------------------------------------------------- (b) + (c)
out="$("$PYTHON" -m factlog init --target "$SCRATCH")"

if [ "$(active)" = "$MINE" ]; then
  ok "(b) a second init elsewhere leaves the active KB alone"
else
  bad "(b) init hijacked the active KB: $MINE -> $(active)"
fi

if grep -q "left unchanged" <<<"$out" && grep -q "factlog use $SCRATCH" <<<"$out"; then
  ok "(b) init says the active KB was left alone and how to switch"
else
  bad "(b) init was silent about not adopting the new KB: $out"
fi

if [ -d "$SCRATCH/sources" ] && [ -d "$SCRATCH/facts" ]; then
  ok "(c) the new KB is still scaffolded"
else
  bad "(c) init did not scaffold $SCRATCH"
fi

# ------------------------------------------------------------------------ (d)
out="$("$PYTHON" -m factlog init --target "$MINE")"
if grep -q "left unchanged" <<<"$out"; then
  bad "(d) re-init of the active KB wrongly reports it as left unchanged"
else
  ok "(d) re-init of the already-active KB is not reported as a conflict"
fi

# ------------------------------------------------------------------------ (e)
"$PYTHON" -m factlog use "$SCRATCH" >/dev/null
if [ "$(active)" = "$SCRATCH" ]; then
  ok "(e) 'factlog use' still switches deliberately"
else
  bad "(e) 'factlog use' failed to switch (got '$(active)')"
fi

# ------------------------------------------------------------------------ (f)
# setup adopts its target by design, but must not slip the replacement past the
# user. Skip the dependency install; --target still runs the init+config path.
"$PYTHON" -m factlog use "$MINE" >/dev/null
out="$("$PYTHON" -m factlog setup --target "$SCRATCH" 2>&1 || true)"
if [ "$(active)" = "$SCRATCH" ]; then
  ok "(f) setup adopts its target"
else
  bad "(f) setup did not adopt its target (got '$(active)')"
fi
if grep -q "CHANGED active KB" <<<"$out"; then
  ok "(f) setup announces that it replaced a different active KB"
else
  bad "(f) setup replaced the active KB without saying so"
fi

echo "---"
echo "passed: $pass, failed: $fail"
[ "$fail" -eq 0 ]
