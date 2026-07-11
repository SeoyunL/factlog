#!/usr/bin/env bash
# #227: a typed literal that does not parse must appear in facts/logic_report.txt.
# The unit test alone cannot catch this — it passes even when the collector is
# never wired into the report, which was the bug. This pins the report itself.
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
PY="${FACTLOG_PY:-$HOME/.factlog-venv/bin/python}"
export PYTHONPATH="$ROOT"
fails=0
check() { if [ "$2" = "$3" ]; then echo "  ok: $1"; else echo "FAIL: $1 (want $3, got $2)"; fails=$((fails+1)); fi; }

KB="$(mktemp -d)/kb"
export XDG_CONFIG_HOME="$(mktemp -d)"
"$PY" -m factlog init --target "$KB" >/dev/null 2>&1 || { echo "SKIP: init unavailable"; exit 0; }
printf 'a\n' > "$KB/sources/a.md"
printf 'subject,relation,object,source,status,confidence,note\n' > "$KB/facts/candidates.csv"
printf 'A,league_rank,rank 3,sources/a.md,accepted,0.9,\n' >> "$KB/facts/candidates.csv"
printf 'B,league_rank,3rd,sources/a.md,accepted,0.9,\n' >> "$KB/facts/candidates.csv"
printf 'league_rank\n' > "$KB/policy/attribute-relations.md"
printf -- '- `league_rank` : ordinal as rankval\n' > "$KB/policy/typed-relations.md"

FACTLOG_ROOT="$KB" "$PY" tools/compile_facts.py >/dev/null 2>&1
FACTLOG_ROOT="$KB" "$PY" tools/run_logic_check.py >/dev/null 2>&1
REPORT="$KB/facts/logic_report.txt"
[ -f "$REPORT" ] || { echo "SKIP: no report (engine unavailable)"; exit 0; }

# (a) the unparseable fact is named in the report, not just on stderr
grep -q 'rank 3' "$REPORT"; check "(a) the dropped fact is named in the report" "$?" "0"
# (b) the report does not claim zero warnings while a fact is missing from typed queries
grep -qE '^warnings: 0$' "$REPORT"; [ "$?" -ne 0 ]; check "(b) report does not say warnings: 0" "$?" "0"
# (c) the consequence — exclusion from the comparison predicate — is stated
grep -q 'EXCLUDED' "$REPORT"; check "(c) the report states the fact is excluded" "$?" "0"
# (d) the parseable fact is NOT warned about (no crying wolf)
grep -q '3rd' "$REPORT"; [ "$?" -ne 0 ]; check "(d) the parseable fact is not warned about" "$?" "0"

echo
if [ "$fails" -eq 0 ]; then echo "typed-parse report: all passed"; else echo "typed-parse report: $fails failed"; exit 1; fi
