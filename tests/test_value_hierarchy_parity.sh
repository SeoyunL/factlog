#!/usr/bin/env bash
# tests/test_value_hierarchy_parity.sh — report and ask must agree (#211)
#
# The value hierarchy is applied in three places: the gate (common.classify_query),
# the evaluator (ask_router.evaluate_relation), and the report
# (run_logic_check.relation_results). If they do not read the same declarations,
# `/factlog ask` and `/factlog check` answer the SAME question differently.
#
# That is exactly what the first version of this feature did: the report returned
# the subtype rows while ask, whose gate still judged the object against the raw
# accepted vocabulary, either routed to wiki or — worse — asserted
# "no such fact (verified negative)". An assertion that is wrong is worse than the
# silent omission the feature set out to fix. Unit tests on the matchers alone did
# not catch it, because the gate sits in front of the matcher.
#
# Pins, on one KB with `코호트연구 ⊂ 관찰연구` declared:
#   (a) the report returns the subtype rows for a broad query
#   (b) ask ROUTES TO THE ENGINE for that query (not wiki)
#   (c) ask returns the SAME row count as the report
#   (d) the broad value need not appear in any accepted fact — that is the point
#   (e) a narrow query still does not return the broad row (subsumption is one-way)
#
# Usage: bash tests/test_value_hierarchy_parity.sh

set -euo pipefail

TMP_ROOT="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$TMP_ROOT"' EXIT

export XDG_CONFIG_HOME="$TMP_ROOT/cfg"  # isolate the active-KB config (#62)

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$PLUGIN_ROOT${PYTHONPATH:+:$PYTHONPATH}"
PYTHON="${PYTHON:-python3}"

if ! "$PYTHON" -c "import pyrewire" >/dev/null 2>&1; then
  echo "SKIP: pyrewire not installed; the report half of this parity test needs the engine"
  exit 0
fi

pass=0
fail=0
ok() { echo "PASS: $*"; pass=$((pass + 1)); }
bad() { echo "FAIL: $*" >&2; fail=$((fail + 1)); }

KB="$TMP_ROOT/kb"
"$PYTHON" -m factlog init --target "$KB" >/dev/null
printf 'a\n' > "$KB/sources/a.md"
# NOTE: no row is filed as "관찰연구". The broad value exists ONLY in the
# declaration — the natural way to use a hierarchy, and the case that made the
# old gate assert a false verified negative.
printf '%s\n%s\n%s\n' \
  'subject,relation,object,source,status,confidence,note' \
  'P2,연구유형,코호트연구,sources/a.md,accepted,0.90,' \
  'P3,연구유형,단면연구,sources/a.md,accepted,0.90,' \
  > "$KB/facts/candidates.csv"
printf -- '- 연구유형: 코호트연구 ⊂ 관찰연구\n- 연구유형: 단면연구 ⊂ 관찰연구\n' \
  > "$KB/policy/value-hierarchy.md"

BROAD='relation(P, "연구유형", "관찰연구")?'
NARROW='relation(P, "연구유형", "코호트연구")?'

( cd "$KB" && FACTLOG_ROOT="$KB" "$PYTHON" "$PLUGIN_ROOT/tools/compile_facts.py" >/dev/null )
printf '%s\n' "$BROAD" > "$KB/facts/query.dl"
( cd "$KB" && FACTLOG_ROOT="$KB" "$PYTHON" "$PLUGIN_ROOT/tools/run_logic_check.py" >/dev/null )

report_rows="$(sed -n 's/^- relation results: \([0-9]*\) rows.*/\1/p' "$KB/facts/logic_report.txt" | head -1)"
if [ "$report_rows" = "2" ]; then
  ok "(a)(d) the report returns both subtype rows for the broad query"
else
  bad "(a)(d) report returned '$report_rows' rows, expected 2"
fi

route="$("$PYTHON" "$PLUGIN_ROOT/tools/ask_router.py" validate "$BROAD" --target "$KB" \
  | "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["route"])')"
if [ "$route" = "engine" ]; then
  ok "(b) ask routes the broad query to the engine"
else
  bad "(b) ask routed the broad query to '$route' — the gate does not know the hierarchy"
fi

ask_rows="$("$PYTHON" "$PLUGIN_ROOT/tools/ask_router.py" evaluate "$BROAD" --target "$KB" \
  | "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["count"])')"
if [ "$ask_rows" = "$report_rows" ]; then
  ok "(c) ask and the report agree ($ask_rows rows)"
else
  bad "(c) ask says $ask_rows rows, the report says $report_rows — they disagree"
fi

narrow_rows="$("$PYTHON" "$PLUGIN_ROOT/tools/ask_router.py" evaluate "$NARROW" --target "$KB" \
  | "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["count"])')"
if [ "$narrow_rows" = "1" ]; then
  ok "(e) subsumption stays one-way (narrow query returns only its own row)"
else
  bad "(e) narrow query returned $narrow_rows rows, expected 1"
fi

echo "---"
echo "passed: $pass, failed: $fail"
[ "$fail" -eq 0 ]
