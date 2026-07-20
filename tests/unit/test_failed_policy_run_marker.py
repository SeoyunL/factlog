# SPDX-License-Identifier: Apache-2.0
"""A failed policy run says so in runs/, and says which files are its own (#372).

tools/generate_logic_policy.py writes PROMPT_OUT before any gate and RESPONSE_OUT
between two of them, so a run that raises part-way leaves runs/ holding files from two
different runs with nothing to tell them apart. Measured on main 4b40fac (sample-kb,
a clean run then a control character in a backtick relation name): rc=1, prompt.md
c3dd879a -> a237478b, response.json still 56ca7221 and trace.md still 3b618ecb — the
previous run's bytes. The directory then reads as the audit record of a run that never
happened, which no exit code or stderr message contradicts.

Deleting the leftovers was rejected as the fix: it destroys the only evidence of the
failing run and still leaves a directory matching no run (the earlier run's response
and trace, minus its prompt). So the run states the accounting instead, in
runs/natural-language-to-policy-failed.md, and its absence is the signal that runs/
describes exactly one run.

The failure is NOT specific to the control-char gate. A canonical/non-canonical clash
raises in normalized_rules, one line past RESPONSE_OUT, and leaves BOTH files behind —
which is why test_conflicting_canonical_marker_run_owns_prompt_and_response also serves
as the reachability pin for that path.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

MARKER = "natural-language-to-policy-failed.md"
PROMPT = "natural-language-to-policy-prompt.md"
RESPONSE = "natural-language-to-policy-response.json"
TRACE = "natural-language-to-policy-trace.md"

# `factlog init` ships a logic-policy.md with no compilable bullets, so every run
# against a bare KB fails ("no supported policy bullets"). The success cases need a real
# rule; this is sample-kb's first bullet.
GOOD_MD = (
    "# Logic policy\n\n## Rules\n\n"
    "- [bidirectional_check] Facts with the `develops` relation require review when a "
    "matching `developed_by` relation also exists.\n"
)
CONTROL_CHAR_MD = "# Logic policy\n\n## Rules\n\n- [retracted] a doc that `cites\x01evil` is retracted.\n"
CANONICAL_CLASH_MD = (
    "# Logic policy\n\n## Rules\n\n"
    "- [alpha] a doc that `develops` needs review.\n"
    "- [alpha] {canonical} a doc that `develops` needs review.\n"
)


@pytest.fixture
def kb(tmp_path):
    root = tmp_path / "kb"
    subprocess.run(
        [sys.executable, "-m", "factlog", "init", "--target", str(root)],
        capture_output=True, check=True,
    )
    (root / "policy" / "logic-policy.md").write_text(GOOD_MD, encoding="utf-8")
    return root


def _generate(kb):
    return subprocess.run(
        [sys.executable, str(Path("tools") / "generate_logic_policy.py")],
        capture_output=True, text=True,
        env={**os.environ, "FACTLOG_ROOT": str(kb), "PYTHONPATH": os.getcwd()},
    )


def _marker(kb) -> str:
    path = kb / "runs" / MARKER
    assert path.is_file(), f"no {MARKER} in {sorted(p.name for p in (kb / 'runs').iterdir())}"
    return path.read_text(encoding="utf-8")


def _section(marker: str, heading: str) -> list[str]:
    """The bullet names listed under one '## heading' of the marker."""
    blocks = marker.split(f"## {heading}\n")
    assert len(blocks) == 2, f"heading '{heading}' not found exactly once in:\n{marker}"
    names = []
    for line in blocks[1].splitlines():
        if line.startswith("## "):
            break
        if line.startswith("- "):
            names.append(line[2:])
    return names


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def test_control_char_failure_marks_the_run_and_owns_the_prompt(kb):
    (kb / "policy" / "logic-policy.md").write_text(CONTROL_CHAR_MD, encoding="utf-8")
    proc = _generate(kb)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    marker = _marker(kb)
    # The prompt is the one file this run wrote before the gate fired.
    assert _section(marker, "Written by this run") == [PROMPT], marker
    # The marker never replaces the diagnosis; it records which files carry it.
    assert "#359" in proc.stderr, proc.stderr


def test_conflicting_canonical_marker_run_owns_prompt_and_response(kb):
    # Reachability pin: this input dies in normalized_rules, PAST RESPONSE_OUT, so the
    # deterministic path DOES produce a response.json on a failing run. Any change that
    # makes only the prompt appear here means the write order moved.
    (kb / "policy" / "logic-policy.md").write_text(CANONICAL_CLASH_MD, encoding="utf-8")
    proc = _generate(kb)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "canonical" in (proc.stdout + proc.stderr), proc.stdout + proc.stderr
    marker = _marker(kb)
    assert _section(marker, "Written by this run") == [PROMPT, RESPONSE], marker
    assert _section(marker, "Not present") == [TRACE], marker


def test_failure_after_success_names_the_stale_files_as_not_its_own(kb):
    # The mixed-vintage case itself: run N's prompt beside run N-1's response and trace.
    assert _generate(kb).returncode == 0
    kept = {name: _md5(kb / "runs" / name) for name in (RESPONSE, TRACE)}
    (kb / "policy" / "logic-policy.md").write_text(CONTROL_CHAR_MD, encoding="utf-8")
    assert _generate(kb).returncode == 1
    # The two files really are the previous run's bytes, not rewritten ones ...
    assert {name: _md5(kb / "runs" / name) for name in kept} == kept
    # ... and the marker says so rather than leaving a reader to compare hashes.
    marker = _marker(kb)
    assert _section(marker, "Present, not written by this run") == [RESPONSE, TRACE], marker
    assert _section(marker, "Written by this run") == [PROMPT], marker


def test_a_successful_run_leaves_no_marker(kb):
    proc = _generate(kb)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not (kb / "runs" / MARKER).exists()


def test_a_success_after_a_failure_removes_the_marker(kb):
    good = (kb / "policy" / "logic-policy.md").read_text(encoding="utf-8")
    (kb / "policy" / "logic-policy.md").write_text(CONTROL_CHAR_MD, encoding="utf-8")
    assert _generate(kb).returncode == 1
    assert (kb / "runs" / MARKER).is_file()
    (kb / "policy" / "logic-policy.md").write_text(good, encoding="utf-8")
    proc = _generate(kb)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    # Absence is the whole signal, so a stale marker would be worse than none.
    assert not (kb / "runs" / MARKER).exists()


def test_marker_does_not_change_the_bytes_a_successful_run_writes(kb):
    names = (PROMPT, RESPONSE, TRACE)
    assert _generate(kb).returncode == 0
    first = {name: _md5(kb / "runs" / name) for name in names}
    assert _generate(kb).returncode == 0
    assert {name: _md5(kb / "runs" / name) for name in names} == first
    # Pinned against the pre-#372 output, measured by running base 4b40fac's
    # tools/generate_logic_policy.py over a KB built exactly like this fixture: the
    # accounting lives in its own file and injects no header into these three. A prompt
    # exists to hand a model the author's .md verbatim, so a header would defeat it.
    assert first == {
        PROMPT: "88b25f0fdd4107b6e7955eb9cef5d0ce",
        RESPONSE: "75819dade89ef4c790a321c8abcdf07d",
        TRACE: "ec08fc7be77a9573b55102cefad059a7",
    }, first


def test_the_marker_is_deterministic(kb):
    # No wall-clock time, no absolute paths: same input, same marker bytes. A timestamp
    # here would make every failed run a diff even when nothing about it changed.
    (kb / "policy" / "logic-policy.md").write_text(CONTROL_CHAR_MD, encoding="utf-8")
    assert _generate(kb).returncode == 1
    first = _marker(kb)
    assert _generate(kb).returncode == 1
    assert _marker(kb) == first
