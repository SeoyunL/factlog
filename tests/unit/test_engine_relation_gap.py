# SPDX-License-Identifier: Apache-2.0
"""Catch a silently-emptied engine input: disk has facts, the engine parsed none (#308).

The logic report's `engine facts` line counts DISK rows (load_accepted_facts), so it
cannot see the engine's own relation EDB emptying underneath it -- the blind spot behind
#305's vacuous pass (report said `engine facts: 7` while the engine evaluated over
nothing). `run_wirelog` now surfaces the engine's OWN parsed relation extent under
`inferred["relation"]` (read via `preview_inline_facts`, since an EDB never appears as a
step() delta), and `run_logic_check.engine_relation_gap` compares the two independent
readers. It is the LAST NET: #305's guard rejects the known causes (relation rule-head /
.decl re-declaration) loudly at policy load; this catches an unknown cause that slips
past. Conservative: only the TOTAL-emptying (0) case fires, so a healthy KB never trips.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from run_logic_check import engine_relation_gap


def _facts(n):
    return [{"subject": f"s{i}", "relation": "uses", "object": f"o{i}"} for i in range(n)]


class TestEngineRelationGapHelper:
    """Pure function -- no engine, runs everywhere."""

    def test_disk_facts_but_engine_zero_is_an_error(self):
        msg = engine_relation_gap(_facts(7), {"relation": set(), "path": {("s0", "o0")}})
        assert msg is not None
        assert "7 accepted fact(s) on disk" in msg
        assert "0 relation atoms" in msg

    def test_a_missing_relation_key_counts_as_zero(self):
        # inferred without a "relation" key at all is still the gap (0 engine atoms).
        assert engine_relation_gap(_facts(3), {"path": set()}) is not None

    def test_engine_has_relation_atoms_is_fine(self):
        atoms = {("s0", "uses", "o0"), ("s1", "uses", "o1")}
        assert engine_relation_gap(_facts(2), {"relation": atoms}) is None

    def test_an_empty_kb_does_not_fire(self):
        # No disk facts -> a legitimately empty engine, not a gap.
        assert engine_relation_gap([], {"relation": set()}) is None
        assert engine_relation_gap([], {}) is None

    def test_it_is_conservative_about_count_mismatch(self):
        # Only the TOTAL-emptying case fires. A partial (engine < disk) is NOT flagged
        # here -- a non-zero engine count is treated as "the engine got its input".
        assert engine_relation_gap(_facts(7), {"relation": {("s0", "uses", "o0")}}) is None


# --- Engine-backed seam + contract -------------------------------------------
try:
    import pyrewire  # noqa: F401

    _HAVE_ENGINE = True
except ImportError:  # pragma: no cover - depends on the install
    _HAVE_ENGINE = False


def _kb(tmp_path):
    kb = tmp_path / "kb"
    subprocess.run(
        [sys.executable, "-m", "factlog", "init", "--target", str(kb)],
        capture_output=True, check=True,
    )
    (kb / "sources" / "a.md").write_text("a\n")
    rows = [("Claude Code", "developed_by", "Anthropic"), ("Anthropic", "develops", "Claude Code")]
    lines = ["subject,relation,object,source,status,confidence,note"]
    lines += [f"{s},{r},{o},sources/a.md,accepted,0.9," for s, r, o in rows]
    (kb / "facts" / "candidates.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    subprocess.run(
        [sys.executable, str(Path("tools") / "compile_facts.py")],
        capture_output=True,
        env={**os.environ, "FACTLOG_ROOT": str(kb), "PYTHONPATH": os.getcwd()},
        check=True,
    )
    return kb


def _run(kb, script):
    return subprocess.run(
        [sys.executable, "-c", "import os, sys; sys.path.insert(0, os.getcwd()); "
         "sys.path.insert(0, os.path.join(os.getcwd(), 'tools'))\n" + script],
        capture_output=True, text=True,
        env={**os.environ, "FACTLOG_ROOT": str(kb), "PYTHONPATH": os.getcwd()},
    )


@pytest.mark.skipif(not _HAVE_ENGINE, reason="pyrewire not installed")
class TestRunLogicCheckSeam:
    """The seam #305's guard bypasses: with the engine's relation forced empty (standing
    in for any unknown cause), run_logic_check must error and exit non-zero -- not report
    a vacuous 'no contradictions' over an emptied engine."""

    def test_emptied_engine_relation_makes_check_exit_nonzero(self, tmp_path):
        kb = _kb(tmp_path)
        # Monkeypatch run_wirelog to return the real inferred but with relation emptied,
        # simulating a silent engine-input drop the #305 guard did not catch.
        script = (
            "import run_logic_check as rlc\n"
            "_orig = rlc.run_wirelog\n"
            "def _fake():\n"
            "    inf = _orig()\n"
            "    inf['relation'] = set()\n"
            "    return inf\n"
            "rlc.run_wirelog = _fake\n"
            "rc = rlc.main()\n"
            "print('RC', rc)\n"
        )
        out = _run(kb, script)
        assert "RC 1" in out.stdout, out.stdout + out.stderr
        report = (kb / "facts" / "logic_report.txt").read_text(encoding="utf-8")
        assert "engine input gap" in report
        assert "errors: 1" in report

    def test_healthy_kb_does_not_trip_the_gap(self, tmp_path):
        kb = _kb(tmp_path)
        out = _run(kb, "import run_logic_check as rlc\nprint('RC', rlc.main())")
        assert "RC None" in out.stdout, out.stdout + out.stderr
        report = (kb / "facts" / "logic_report.txt").read_text(encoding="utf-8")
        assert "engine input gap" not in report
        assert "errors: 0" in report


@pytest.mark.skipif(not _HAVE_ENGINE, reason="pyrewire not installed")
class TestRealEngineContract:
    """The signal only works if run_wirelog genuinely surfaces the engine's relation
    extent. Pin that contract: a healthy KB's inferred["relation"] is non-empty and
    matches the disk fact count (both read the same accepted.dl)."""

    def test_run_wirelog_surfaces_relation_atoms(self, tmp_path):
        kb = _kb(tmp_path)
        out = _run(kb, "import factlog.common as c\n"
                       "facts = c.load_accepted_facts()\n"
                       "inf = c.run_wirelog()\n"
                       "print(len(facts), len(inf.get('relation', set())))")
        disk, engine = out.stdout.split()
        assert int(engine) > 0, out.stdout + out.stderr
        assert disk == engine  # both parse the same accepted.dl


@pytest.mark.skipif(not _HAVE_ENGINE, reason="pyrewire not installed")
class TestNoRegressionOnDuplicates:
    """A KB whose candidates carry duplicate rows (deduped at compile) must not trip the
    gap -- the engine still holds the deduped relation atoms."""

    def test_dedup_kb_reports_no_gap(self, tmp_path):
        kb = tmp_path / "kb"
        subprocess.run(
            [sys.executable, "-m", "factlog", "init", "--target", str(kb)],
            capture_output=True, check=True,
        )
        (kb / "sources" / "a.md").write_text("a\n")
        # The same fact twice -> compile dedups to one relation atom.
        lines = ["subject,relation,object,source,status,confidence,note",
                 "A,uses,B,sources/a.md,accepted,0.9,",
                 "A,uses,B,sources/a.md,accepted,0.9,"]
        (kb / "facts" / "candidates.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
        subprocess.run(
            [sys.executable, str(Path("tools") / "compile_facts.py")],
            capture_output=True,
            env={**os.environ, "FACTLOG_ROOT": str(kb), "PYTHONPATH": os.getcwd()},
            check=True,
        )
        out = _run(kb, "import run_logic_check as rlc\nprint('RC', rlc.main())")
        assert "RC None" in out.stdout, out.stdout + out.stderr
        assert "engine input gap" not in (kb / "facts" / "logic_report.txt").read_text(encoding="utf-8")
