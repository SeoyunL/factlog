# SPDX-License-Identifier: Apache-2.0
"""The rebuild ratchet must not REFUSE a fact runs/ still assert (#481).

merge's ratchet (#218) refuses to rebuild candidates.csv when doing so would drop a
row a human ruled on that the current runs/ no longer assert. It decides "no longer
assert" by comparing the preserved key of the candidates.csv row against the keys of
the normalized run rows. Those two keys have to be THE SAME identity -- common.fact_key
(canonical_amount on the object, NFC + anchor-strip on the source).

Before #481 the preserved keys hand-built the 4-tuple raw, so a candidates.csv value
merge did NOT write -- a hand-edit, or `amend --set-object` with a non-canonical amount,
or an NFD-decomposed macOS filename -- drifted from the run key for the very same fact.
The ratchet then saw a still-asserted, human-confirmed fact as "destroyed" and REFUSED,
leaving merge blocked for a reason the user cannot see. These drive the whole tool
end-to-end and pin that such a fact rebuilds cleanly, keeping its human status.
"""
from __future__ import annotations

import csv
import subprocess
import sys
import unicodedata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MERGE = ROOT / "tools" / "merge_candidates.py"

NFC = unicodedata.normalize("NFC", "가나")
NFD = unicodedata.normalize("NFD", "가나")


def _init_kb(tmp_path):
    kb = tmp_path / "wiki"
    env = _env(tmp_path)
    subprocess.run(
        [sys.executable, "-m", "factlog", "init", "--target", str(kb)],
        cwd=ROOT, env=env, check=True, capture_output=True, text=True,
    )
    return kb


def _env(tmp_path):
    import os
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["XDG_CONFIG_HOME"] = str(tmp_path / "cfg")
    return env


def _write_source(kb, name):
    (kb / "sources").mkdir(exist_ok=True)
    (kb / "sources" / name).write_text("# note\n", encoding="utf-8")


def _write_run(kb, subject, relation, obj, source):
    (kb / "runs").mkdir(exist_ok=True)
    row = {
        "subject": subject, "relation": relation, "object": obj, "source": source,
        "status": "candidate", "confidence": 0.9, "note": "",
    }
    import json
    (kb / "runs" / "r1.json").write_text(json.dumps([row]), encoding="utf-8")


def _write_candidates(kb, subject, relation, obj, source, status):
    with (kb / "facts" / "candidates.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["subject", "relation", "object", "source", "status", "confidence", "note"])
        w.writerow([subject, relation, obj, source, status, "0.90", ""])


def _merge(kb, tmp_path):
    return subprocess.run(
        [sys.executable, str(MERGE), "--wiki", str(kb)],
        cwd=ROOT, env=_env(tmp_path), capture_output=True, text=True,
    )


def _status_of(kb, subject, relation):
    with (kb / "facts" / "candidates.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if (row["subject"], row["relation"]) == (subject, relation):
                return row["status"]
    return None


# (csv object/source a human hand-edited in, run object/source the extractor emits)
CASES = {
    # the issue's exact reproduction: non-canonical amount, hand-confirmed
    "noncanon_amount": ("amount(7,억)", "sources/note.md", "amount(7,억)", "sources/note.md"),
    # candidates.csv canonical, run pre-canonical -- the reverse fold direction
    "quoted_amount_vs_bare_run": ('amount(7,"억")', "sources/note.md", "amount(7,억)", "sources/note.md"),
    # NFD-decomposed filename in candidates.csv vs NFC run source (macOS hands out NFD)
    "nfd_source": ("X", f"sources/{NFD}.md", "X", f"sources/{NFC}.md"),
    # NFC in candidates.csv vs NFD run source (the mirror)
    "nfc_source": ("X", f"sources/{NFC}.md", "X", f"sources/{NFD}.md"),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_rebuild_not_refused_when_runs_still_assert(tmp_path, case):
    csv_obj, csv_src, run_obj, run_src = CASES[case]
    kb = _init_kb(tmp_path)
    # the source file is stored NFC on disk; both csv_src and run_src name the same doc
    _write_source(kb, unicodedata.normalize("NFC", Path(csv_src).name))
    _write_run(kb, "A", "costs", run_obj, run_src)
    _write_candidates(kb, "A", "costs", csv_obj, csv_src, "confirmed")

    result = _merge(kb, tmp_path)

    assert "REFUSING to rebuild" not in result.stderr, (
        f"{case}: ratchet refused a fact runs/ still assert\n{result.stderr}"
    )
    # the human's confirmed status must survive the rebuild
    assert _status_of(kb, "A", "costs") == "confirmed", (
        f"{case}: confirmed status not preserved\nstdout={result.stdout}\nstderr={result.stderr}"
    )
