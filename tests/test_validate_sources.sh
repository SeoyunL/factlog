#!/usr/bin/env bash
# tests/test_validate_sources.sh — validate.py accepts runs/sources/ origins (#24)
#
# runs/sources/ is a second valid source root (factlog ingest writes converted
# text there). This pins that validate.py accepts a runs/sources/-prefixed
# `source` exactly like a sources/-prefixed one, still rejects a bare filename,
# and that validate_source_ref resolves a runs/sources/ file.
#
# Asserts on the specific "source must start with" message so unrelated
# structural validations in the KB do not affect the result.
#
# Usage: bash tests/test_validate_sources.sh  -> 0 if all pass, 1 otherwise.

set -euo pipefail

export XDG_CONFIG_HOME="$(mktemp -d)/factlog-test-cfg"  # isolate active-KB config (#62) from the dev machine

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$PLUGIN_ROOT${PYTHONPATH:+:$PYTHONPATH}"
PYTHON="${PYTHON:-python3}"
VALIDATE="$PLUGIN_ROOT/tools/validate.py"
HEADER="subject,relation,object,source,status,confidence,note"

pass=0
fail=0
ok() { echo "PASS: $*"; pass=$((pass + 1)); }
bad() { echo "FAIL: $*" >&2; fail=$((fail + 1)); }

KB="$(mktemp -d)/wiki"
"$PYTHON" -m factlog init --target "$KB" >/dev/null
mkdir -p "$KB/runs/sources"
printf '# converted\n\nWidgetX integrates ToolA.\n' > "$KB/runs/sources/conv.md"
printf '# original\n\nAcme uses FastAPI.\n' > "$KB/sources/orig.md"

# write a candidates.csv with the given source value (one row)
write_csv() { printf '%s\nWidgetX,integrates,ToolA,%s,confirmed,0.90,\n' "$HEADER" "$1" > "$KB/facts/candidates.csv"; }
prefix_err() { "$PYTHON" "$VALIDATE" "$KB" 2>&1 | grep -c "source must start with" || true; }

# runs/sources/ source -> must NOT raise the prefix error
write_csv "runs/sources/conv.md"
if [ "$(prefix_err)" = "0" ]; then ok "runs/sources/ source accepted (no prefix error)"; else bad "runs/sources/ source wrongly rejected"; fi

# sources/ source -> must NOT raise the prefix error (unchanged behavior)
write_csv "sources/orig.md"
if [ "$(prefix_err)" = "0" ]; then ok "sources/ source still accepted"; else bad "sources/ source wrongly rejected"; fi

# bare filename -> MUST raise the prefix error
write_csv "conv.md"
if [ "$(prefix_err)" -ge 1 ]; then ok "bare filename still rejected"; else bad "bare filename was not rejected"; fi

# runs/sources/ ref to a MISSING file -> source-existence error (not prefix)
write_csv "runs/sources/missing.md"
out="$("$PYTHON" "$VALIDATE" "$KB" 2>&1 || true)"
if printf '%s' "$out" | grep -q "source must start with"; then bad "missing runs/sources file raised a prefix error (should be existence error)"; else ok "missing runs/sources file passes prefix check (handed to existence check)"; fi
if printf '%s' "$out" | grep -q "source file does not exist"; then ok "validate_source_ref resolves runs/sources/ (flags the missing file)"; else bad "missing runs/sources file not flagged by validate_source_ref"; fi

echo ""
echo "========================================"
echo "test_validate_sources: $pass passed, $fail failed"
echo "========================================"
[ "$fail" -eq 0 ]
