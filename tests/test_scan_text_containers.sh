#!/usr/bin/env bash
# tests/test_scan_text_containers.sh — --scan converts RTF/HTML (#222)
#
# `ingest --scan` sniffs file CONTENT to avoid converting a mislabelled .pdf that
# is really plain text. RTF and HTML are text-BASED containers, so they always
# tripped that sniff and were skipped — forever, because /factlog sync runs
# --scan as its first step. Their markup (RTF control words, HTML tags) then went
# into extraction as if it were prose.
#
# And no warning fired: merge_candidates' "binary with no conversion" check also
# uses a content sniff, so it did not count them either. README calls both formats
# "Auto-converted" and promises the warning makes silent non-ingestion visible.
#
# Pins:
#   (a) --scan converts .rtf and .html (the extension decides, not the sniff)
#   (b) the sniff still protects a MISLABELLED binary (.pdf/.docx holding text)
#   (c) a real binary is still converted
#   (d) a plain .md is still left alone (not a conversion job)
#   (e) an unconverted text container IS reported by merge_candidates
#   (f) once converted, that warning goes away
#
# Usage: bash tests/test_scan_text_containers.sh

set -euo pipefail

TMP_ROOT="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$TMP_ROOT"' EXIT
export XDG_CONFIG_HOME="$TMP_ROOT/cfg"

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$PLUGIN_ROOT${PYTHONPATH:+:$PYTHONPATH}"
PYTHON="${PYTHON:-python3}"
MERGE="$PLUGIN_ROOT/tools/merge_candidates.py"

pass=0
fail=0
ok() { echo "PASS: $*"; pass=$((pass + 1)); }
bad() { echo "FAIL: $*" >&2; fail=$((fail + 1)); }

KB="$TMP_ROOT/kb"
"$PYTHON" -m factlog init --target "$KB" >/dev/null
printf '<html><body><p>hi</p></body></html>\n' > "$KB/sources/page.html"
printf 'plain prose\n' > "$KB/sources/note.md"
printf 'this is plain text, not really a pdf\n' > "$KB/sources/fake.pdf"

# Converter availability gates ONLY the pins that need a converter, and is decided
# BEFORE the run. A blanket skip would take the guards that need no converter
# ((b), (d), (e)) down with it — the same "a quiet guard is a dead guard" trap, in
# a different shape.
have_html=0; command -v pandoc >/dev/null 2>&1 && have_html=1
have_rtf=0;  { command -v textutil >/dev/null 2>&1 || command -v pandoc >/dev/null 2>&1; } && have_rtf=1

printf '{\\rtf1\\ansi hello}\n' > "$KB/sources/memo.rtf"
"$PYTHON" -m factlog ingest --scan --target "$KB" >/dev/null 2>&1 || true

if [ "$have_html" = 1 ]; then
  if find "$KB/runs/sources" -name 'page.html.*' | grep -q .; then
    ok "(a) --scan converted the HTML container"
  else
    bad "(a) --scan skipped the HTML container — its markup goes into extraction as prose"
  fi
else
  echo "SKIP: pandoc absent; cannot pin HTML conversion"
fi

if [ "$have_rtf" = 1 ]; then
  if find "$KB/runs/sources" -name 'memo.rtf.*' | grep -q .; then
    ok "(a) --scan converted the RTF container"
  else
    bad "(a) --scan skipped the RTF container — its control words go into extraction"
  fi
else
  echo "SKIP: neither textutil nor pandoc; cannot pin RTF conversion"
fi

if find "$KB/runs/sources" -name 'fake.pdf.*' | grep -q .; then
  bad "(b) the sniff no longer protects a mislabelled .pdf — it was converted"
else
  ok "(b) a mislabelled .pdf is still left alone (the sniff still does its job)"
fi

if find "$KB/runs/sources" -name 'note.md.*' | grep -q .; then
  bad "(d) a plain .md was needlessly converted"
else
  ok "(d) a plain .md is still not a conversion job"
fi

# ------------------------------------------------------------------ (c)
# A REAL binary must still convert — the exception must not have narrowed --scan.
if command -v textutil >/dev/null 2>&1; then
  printf 'real\n' > "$TMP_ROOT/r.txt"
  textutil -convert docx "$TMP_ROOT/r.txt" -output "$KB/sources/real.docx" 2>/dev/null || true
  "$PYTHON" -m factlog ingest --scan --target "$KB" >/dev/null 2>&1 || true
  if find "$KB/runs/sources" -name 'real.docx.*' | grep -q .; then
    ok "(c) a real binary is still converted"
  else
    bad "(c) a real binary stopped converting"
  fi
else
  echo "SKIP: textutil absent; cannot build a real .docx fixture"
fi

# ------------------------------------------------------------------ (e) (f)
KB2="$TMP_ROOT/kb2"
"$PYTHON" -m factlog init --target "$KB2" >/dev/null
printf '<html><body><p>hi</p></body></html>\n' > "$KB2/sources/page.html"

warn="$("$PYTHON" "$MERGE" --wiki "$KB2" 2>&1 >/dev/null || true)"
if grep -q "no runs/sources/ conversion" <<<"$warn"; then
  ok "(e) an unconverted text container is reported — the omission is visible"
else
  bad "(e) an unconverted text container yields no facts and no warning"
fi

"$PYTHON" -m factlog ingest --scan --target "$KB2" >/dev/null 2>&1 || true
warn="$("$PYTHON" "$MERGE" --wiki "$KB2" 2>&1 >/dev/null || true)"
if grep -q "no runs/sources/ conversion" <<<"$warn"; then
  bad "(f) the warning persists after conversion"
else
  ok "(f) the warning clears once the container is converted"
fi

echo "---"
echo "passed: $pass, failed: $fail"
[ "$fail" -eq 0 ]
