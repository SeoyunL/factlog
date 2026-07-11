#!/usr/bin/env bash
# tests/test_eject_path_scope.sh — a path-scoped eject stays in its path (#221)
#
# `eject sub/report.docx` also deleted the conversion of a TOP-LEVEL report.docx —
# a source the user never named — and exited 0. The original survived but its
# conversion did not, so it silently became a coverage gap. README:70 promises the
# opposite ("same-stem files in different folders never collide"), and :616 that
# `eject report.docx` never disturbs another original's conversion.
#
# The cause: the provenance map kept only the original's BASENAME, and the path
# branch compared that against the requested basename, so the conversion's mirrored
# subdirectory was never looked at.
#
# Every pin asserts BOTH directions — the named thing went AND the unnamed thing
# stayed. A one-sided check passes for a "matches nothing at all" implementation,
# which is precisely the failure the first version of this fix introduced.
#
#   (a)(b) a nested eject deletes the nested conversion, keeps the top-level one
#   (c)(d) a top-level eject deletes the top-level one, keeps the nested one
#   (e)    a LEGACY flat conversion (pre-mirroring KB) is still ejectable: its
#          subdir was never recorded, so a path request must fall back to the name
#          rather than silently eject nothing
#   (f)    a `./`-prefixed path is not a miss (both sides normalised)
#   (g)    a headerless conversion is still reachable by path
#   (h)    a path + --delete-original deletes THAT original and no other
#
# Usage: bash tests/test_eject_path_scope.sh

set -euo pipefail

TMP_ROOT="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$TMP_ROOT"' EXIT
export XDG_CONFIG_HOME="$TMP_ROOT/cfg"

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$PLUGIN_ROOT${PYTHONPATH:+:$PYTHONPATH}"
PYTHON="${PYTHON:-python3}"

# Converter availability is decided BEFORE the run, never inferred from "nothing
# was converted" — that inference turns a broken ingest into a green skip.
if ! command -v pandoc >/dev/null 2>&1 && ! command -v textutil >/dev/null 2>&1; then
  echo "SKIP: neither pandoc nor textutil is available; .html cannot be converted here"
  exit 0
fi

pass=0
fail=0
ok() { echo "PASS: $*"; pass=$((pass + 1)); }
bad() { echo "FAIL: $*" >&2; fail=$((fail + 1)); }

top_conv()    { find "$1/runs/sources" -maxdepth 1 -type f -name 'report.html.*' 2>/dev/null | grep -q .; }
nested_conv() { find "$1/runs/sources/sub" -type f -name 'report.html.*' 2>/dev/null | grep -q .; }

# Two originals sharing a basename, in different folders.
new_kb() {
  local kb
  kb="$(mktemp -d "$TMP_ROOT/kb.XXXXXX")/wiki"
  "$PYTHON" -m factlog init --target "$kb" >/dev/null
  mkdir -p "$kb/sources/sub"
  printf 'top\n' > "$kb/sources/report.html"
  printf 'nested\n' > "$kb/sources/sub/report.html"
  # Explicit ingest, not --scan: on this base --scan skips text containers (#222 is
  # a separate branch), and this harness is about eject's path scoping, not scan.
  "$PYTHON" -m factlog ingest "$kb/sources/report.html" --target "$kb" >/dev/null 2>&1
  "$PYTHON" -m factlog ingest "$kb/sources/sub/report.html" --target "$kb" >/dev/null 2>&1
  echo "$kb"
}

KB="$(new_kb)"
if ! top_conv "$KB" || ! nested_conv "$KB"; then
  bad "setup: --scan did not produce both conversions"
  echo "passed: $pass, failed: $fail"
  exit 1
fi

# ------------------------------------------------------------------ (a) (b)
"$PYTHON" -m factlog eject sub/report.html --target "$KB" >/dev/null 2>&1 || true
if nested_conv "$KB"; then
  bad "(a) the nested conversion the user named was NOT deleted"
else
  ok "(a) the nested conversion the user named was deleted"
fi
if top_conv "$KB"; then
  ok "(b) the top-level conversion — never named — survived"
else
  bad "(b) the top-level conversion was deleted: a source the user never named"
fi

# ------------------------------------------------------------------ (c) (d)
KB2="$(new_kb)"
"$PYTHON" -m factlog eject sources/report.html --target "$KB2" >/dev/null 2>&1 || true
if top_conv "$KB2"; then
  bad "(c) the top-level conversion the user named was NOT deleted"
else
  ok "(c) the top-level conversion the user named was deleted"
fi
if nested_conv "$KB2"; then
  ok "(d) the nested conversion — never named — survived"
else
  bad "(d) a top-level request reached into sub/"
fi

# ------------------------------------------------------------------ (e)
# A pre-mirroring KB: a FLAT conversion whose header records only a basename. The
# subdir is not recorded anywhere, so reconstructing one would be a guess — and
# guessing made a path request silently eject nothing on such a KB.
KB3="$(mktemp -d "$TMP_ROOT/kb.XXXXXX")/wiki"
"$PYTHON" -m factlog init --target "$KB3" >/dev/null
mkdir -p "$KB3/sources/sub"
printf 'nested\n' > "$KB3/sources/sub/report.html"
printf -- '<!-- source: report.html | converter: pandoc | date: 2026-01-01 -->\nold\n' \
  > "$KB3/runs/sources/report.md"
"$PYTHON" -m factlog eject sub/report.html --target "$KB3" >/dev/null 2>&1 || true
if [ -f "$KB3/runs/sources/report.md" ]; then
  bad "(e) a legacy flat conversion was left behind — an un-migrated KB cannot eject"
else
  ok "(e) a legacy flat conversion is still ejectable by path"
fi

# ------------------------------------------------------------------ (f)
KB4="$(new_kb)"
"$PYTHON" -m factlog eject ./sub/report.html --target "$KB4" >/dev/null 2>&1 || true
if nested_conv "$KB4"; then
  bad "(f) a ./-prefixed path missed — the two sides are not normalised the same way"
else
  ok "(f) a ./-prefixed path matches"
fi

# ------------------------------------------------------------------ (g)
KB5="$(mktemp -d "$TMP_ROOT/kb.XXXXXX")/wiki"
"$PYTHON" -m factlog init --target "$KB5" >/dev/null
mkdir -p "$KB5/sources/sub" "$KB5/runs/sources/sub"
printf 'nested\n' > "$KB5/sources/sub/report.html"
printf 'no provenance header\n' > "$KB5/runs/sources/sub/report.html.md"
"$PYTHON" -m factlog eject sub/report.html --target "$KB5" >/dev/null 2>&1 || true
if [ -f "$KB5/runs/sources/sub/report.html.md" ]; then
  bad "(g) a headerless conversion is unreachable by path"
else
  ok "(g) a headerless conversion is reachable by its mirrored path"
fi

# ------------------------------------------------------------------ (h)
KB6="$(new_kb)"
"$PYTHON" -m factlog eject sub/report.html --delete-original --target "$KB6" >/dev/null 2>&1 || true
if [ -f "$KB6/sources/sub/report.html" ]; then
  bad "(h) --delete-original left the original in place while reporting success"
else
  ok "(h) a path + --delete-original deletes the original"
fi
if [ -f "$KB6/sources/report.html" ]; then
  ok "(h) --delete-original did not touch the same-named original elsewhere"
else
  bad "(h) --delete-original deleted an original the user never named"
fi

echo "---"
echo "passed: $pass, failed: $fail"
[ "$fail" -eq 0 ]
