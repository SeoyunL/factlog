# SPDX-License-Identifier: Apache-2.0
"""A failed policy run says so in runs/, and says which files are its own (#372).

tools/generate_logic_policy.py writes PROMPT_OUT before any gate and RESPONSE_OUT
between two of them, so a run that raises part-way leaves runs/ holding files from two
different runs with nothing to tell them apart. To reproduce on base 4b40fac: copy
examples/sample-kb, run the tool once, overwrite policy/logic-policy.md with the
CONTROL_CHAR_MD constant below, run it again. Measured — rc=1, prompt.md c3dd879a ->
cc0b8770, response.json still 56ca7221 and trace.md still 3b618ecb, the first run's
bytes. The directory then reads as the audit record of a run that never happened, which
no exit code or stderr message contradicts.

Deleting the leftovers was rejected as the fix: it destroys the only evidence of the
failing run and still leaves a directory matching no run (the earlier run's response
and trace, minus its prompt). So the run states the accounting instead, in
runs/natural-language-to-policy-failed.md, and its absence is the signal that the last
run to write anything under runs/ finished. With one exception, which the code chooses
deliberately: if writing the marker ITSELF fails the run swallows that error to keep the
caller's diagnosis intact, so runs/ can be mixed with nothing saying so. Reproduce by
putting a directory at the marker path. Not being told which gate fired is the worse
outcome of the two, but the absence is not a guarantee.

The marker only ever states what it can support. A run that writes nothing leaves runs/
byte-for-byte as it found it, so it writes no marker and clears none: claiming a mismatch
over an untouched directory would manufacture the audit surface this issue removes, and
the accounting an earlier failure left is still the true one. That is also why a
successful run clears the marker at the END rather than at startup.

The failure is NOT specific to the control-char gate. A canonical/non-canonical clash
raises in normalized_rules, one line past RESPONSE_OUT, and leaves BOTH files behind —
which is why test_conflicting_canonical_marker_run_owns_prompt_and_response also serves
as the reachability pin for that path.
"""
from __future__ import annotations

import hashlib
import os
import re
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


def _break_prompt_template(kb):
    """Make render_prompt fail, i.e. fail the run before it writes any artifact."""
    (kb / "policy" / "prompts" / "natural_language_to_policy.md").write_text(
        "no placeholder here\n", encoding="utf-8"
    )


def test_a_run_that_writes_nothing_leaves_no_marker(kb):
    # The marker must not claim a mismatch that does not exist. render_prompt raises
    # before PROMPT_OUT, so runs/ still holds the previous run's three files and they are
    # a consistent record of it — writing "these do not belong to one run" over them
    # would manufacture exactly the audit surface #372 exists to remove.
    assert _generate(kb).returncode == 0
    before = {name: _md5(kb / "runs" / name) for name in (PROMPT, RESPONSE, TRACE)}
    _break_prompt_template(kb)
    proc = _generate(kb)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert {name: _md5(kb / "runs" / name) for name in before} == before
    assert not (kb / "runs" / MARKER).exists(), (kb / "runs" / MARKER).read_text()


def test_a_run_that_writes_nothing_keeps_an_earlier_marker(kb):
    # The mirror case, and why the marker is cleared on success rather than at startup.
    # Run 1 leaves a real mixture; run 2 touches nothing, so run 1's accounting is still
    # the true description of these files and must survive.
    assert _generate(kb).returncode == 0
    (kb / "policy" / "logic-policy.md").write_text(CONTROL_CHAR_MD, encoding="utf-8")
    assert _generate(kb).returncode == 1
    mixed = _marker(kb)
    _break_prompt_template(kb)
    assert _generate(kb).returncode == 1
    assert _marker(kb) == mixed


def test_the_mixed_vintage_sentence_appears_only_when_something_is_stale(kb):
    mixed_claim = "do not all belong to the same run"
    # Fresh KB: the failing run writes the prompt and nothing older is present, so runs/
    # holds one run's files only and the headline may not say otherwise.
    (kb / "policy" / "logic-policy.md").write_text(CONTROL_CHAR_MD, encoding="utf-8")
    assert _generate(kb).returncode == 1
    only_this_run = _marker(kb)
    assert _section(only_this_run, "Present, not written by this run") == ["(none)"], only_this_run
    assert mixed_claim not in only_this_run, only_this_run
    # Same input over a completed run: now response.json and trace.md ARE older.
    (kb / "policy" / "logic-policy.md").write_text(GOOD_MD, encoding="utf-8")
    assert _generate(kb).returncode == 0
    (kb / "policy" / "logic-policy.md").write_text(CONTROL_CHAR_MD, encoding="utf-8")
    assert _generate(kb).returncode == 1
    assert mixed_claim in _marker(kb), _marker(kb)


def test_failing_to_write_the_marker_does_not_replace_the_verdict(kb):
    # A directory at the marker path makes write_text raise IsADirectoryError, standing in
    # for the full or read-only disk. The caller must still be told which gate fired: the
    # marker is an extra record, so losing it beats swapping the diagnosis for an OSError.
    (kb / "runs" / MARKER).mkdir(parents=True)
    (kb / "policy" / "logic-policy.md").write_text(CONTROL_CHAR_MD, encoding="utf-8")
    proc = _generate(kb)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "#359" in proc.stderr, proc.stderr
    assert "IsADirectoryError" not in proc.stderr, proc.stderr
    assert "Traceback" not in proc.stderr, proc.stderr


def test_an_unclearable_marker_is_reported_rather_than_left_lying(kb):
    # The other half of the asymmetry. On success the marker MUST go, because leaving it
    # would describe three freshly written files as an older run's leftovers. Swallowing
    # the error here would exit 0 over that lie, so the run reports it and says what to do.
    (kb / "runs" / MARKER).mkdir(parents=True)
    proc = _generate(kb)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "could not clear" in proc.stderr, proc.stderr
    assert "Remove it by hand" in proc.stderr, proc.stderr
    assert "Traceback" not in proc.stderr, proc.stderr
    # The run really did its job before tripping on the marker, and says so: printing
    # after the unlink left this path with empty stdout, so rc=1 came with no record of
    # the .dl that had just been written.
    assert (kb / "policy" / "logic-policy.dl").is_file()
    assert "logic-policy.dl" in proc.stdout, proc.stdout
    assert "policy rules:" in proc.stdout, proc.stdout


NO_BULLET_MD = "# Logic policy\n\n## Rules\n\n- nothing compilable here.\n"


def _block_with_a_directory(kb, relative):
    """Make the next write to `relative` raise OSError, standing in for a full disk."""
    path = kb / relative
    if path.exists():
        path.unlink()
    path.mkdir(parents=True)


def _replacing_the_policy(text):
    return lambda kb: (kb / "policy" / "logic-policy.md").write_text(text, encoding="utf-8")


# One mode per raising step of main()'s try block in tools/generate_logic_policy.py,
# in the order that block runs them: fixture_policy_json (both its "no compilable
# policies" exit and its #359 control-char gate), the RESPONSE_OUT write, the canonical
# clash in normalized_rules, the write_trace call, and the .dl swap. Listed against the
# code rather than sampled, because the axis #381 broke stayed invisible while the only
# sample was the #359 gate, whose message holds no path.
#
# Two steps of that block are absent and neither was measured here: compile_policy, for
# which no failing input is known, and smoke_compile, whose pyrewire ParseError this
# harness has no way to provoke from policy text. Reaching either would need a separate
# reachability finding, so they are named rather than silently dropped.
FAILURE_MODES = (
    ("no_compilable_bullets", _replacing_the_policy(NO_BULLET_MD), "SystemExit"),
    ("response_out_unwritable", lambda kb: _block_with_a_directory(kb, f"runs/{RESPONSE}"), "IsADirectoryError"),
    ("control_char_gate", _replacing_the_policy(CONTROL_CHAR_MD), "FactlogError"),
    ("canonical_clash", _replacing_the_policy(CANONICAL_CLASH_MD), "ValueError"),
    ("trace_out_unwritable", lambda kb: _block_with_a_directory(kb, f"runs/{TRACE}"), "IsADirectoryError"),
    ("dl_swap_blocked", lambda kb: _block_with_a_directory(kb, "policy/logic-policy.dl"), "IsADirectoryError"),
)


def _marker_bytes_after(root: Path, setup) -> bytes:
    """Build a KB at `root`, run it clean, break it with `setup`, return the marker."""
    subprocess.run(
        [sys.executable, "-m", "factlog", "init", "--target", str(root)],
        capture_output=True, check=True,
    )
    (root / "policy" / "logic-policy.md").write_text(GOOD_MD, encoding="utf-8")
    assert _generate(root).returncode == 0
    setup(root)
    proc = _generate(root)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    path = root / "runs" / MARKER
    assert path.is_file(), proc.stdout + proc.stderr
    return path.read_bytes()


def test_the_marker_does_not_depend_on_where_the_kb_lives(tmp_path):
    # The axis #381 is about. Two KBs with identical contents at paths of different name
    # length, failing the same way: on base e0cc695 these came out md5 d6e5f67b and
    # 6d11d2cf, because IsADirectoryError stringifies with the absolute paths of the
    # .dl.tmp and the .dl. A marker whose bytes move with the directory it sits in is
    # not the deterministic artifact the rest of this file assumes it is.
    def blocked_dl(kb):
        _block_with_a_directory(kb, "policy/logic-policy.dl")

    short = _marker_bytes_after(tmp_path / "kbA", blocked_dl)
    long = _marker_bytes_after(tmp_path / "kbBBBBBBBBBBBBBBBB", blocked_dl)
    # The mode really is the path-carrying one, so that byte equality below means the
    # paths were normalized and not that the failure changed.
    assert b"IsADirectoryError" in short, short.decode()
    assert short == long, (short.decode(), long.decode())
    assert str(tmp_path).encode() not in short, short.decode()


@pytest.mark.parametrize(
    ("setup", "exception_name"),
    [pytest.param(setup, name, id=mode) for mode, setup, name in FAILURE_MODES],
)
def test_no_failure_mode_writes_where_the_kb_lives_into_the_marker(tmp_path, setup, exception_name):
    short = _marker_bytes_after(tmp_path / "a", setup)
    long = _marker_bytes_after(tmp_path / "bbbbbbbbbbbbbbbb", setup)
    # Reachability first: without this the byte comparison would also pass for a mode
    # that stopped firing, or that started failing somewhere else entirely.
    assert f"\n{exception_name}".encode() in short, short.decode()
    assert short == long, (short.decode(), long.decode())
    assert str(tmp_path).encode() not in short, short.decode()


def test_an_exception_with_no_message_is_named_without_a_dangling_colon():
    # KeyboardInterrupt() and friends stringify to "", and "KeyboardInterrupt: " reads
    # like a message that got truncated on the way out.
    import generate_logic_policy as g

    assert "## Failure\n\nKeyboardInterrupt\n" in g.failure_marker(KeyboardInterrupt(), [g.PROMPT_OUT])
    assert "## Failure\n\nValueError: boom\n" in g.failure_marker(ValueError("boom"), [g.PROMPT_OUT])


FORGERY = "\n## Written by this run\n\n- forged.md\n"


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(FORGERY, id="lf"),
        pytest.param(FORGERY.replace("\n", "\r\n"), id="crlf"),
        pytest.param(FORGERY.replace("\n", "\u2028"), id="line_separator"),
        pytest.param(f"a\x01b\x0c{FORGERY}", id="other_c0"),
    ],
)
def test_no_marker_line_can_open_a_heading(payload):
    # Called directly, because NO exception the subprocess path raises can carry this:
    # the only OS-supplied text past PROMPT_OUT is an OSError filename, and OSError
    # stringifies filenames through %r, so a newline in a path arrives as the two
    # characters \ and n. Measured on python3.12 with
    # OSError(21, 'Is a directory', '/a/kb' + FORGERY + '/x.tmp'): re.findall(r'^## ',
    # str(exc), re.M) == [] and len(str(exc).splitlines()) == 1. So this pins an axis
    # that is closed today only by another type's implementation detail, not a live bug
    # — #381's report claimed a live forgery after counting '## ' as a substring, which
    # answers a different question than "how many headings are there".
    import generate_logic_policy as g

    marker = g.failure_marker(ValueError(payload), [g.PROMPT_OUT])
    assert len(re.findall(r"^## ", marker, re.M)) == 4, marker
    assert _section(marker, "Written by this run") == [PROMPT], marker
    for heading in ("Failure", "Present, not written by this run", "Not present"):
        _section(marker, heading)  # asserts the heading appears exactly once


def _failure_line(marker: str) -> str:
    return marker.split("## Failure\n\n")[1].splitlines()[0]


def test_an_oserror_names_its_files_relative_to_the_kb_and_keeps_its_diagnosis():
    # Determinism must not be bought with diagnosis: errno, strerror and BOTH filenames
    # have to survive. That is why "keep the first line only" was rejected — a rename
    # failure carries its second path there, and the .dl swap is exactly a rename.
    #
    # The five-argument form is deliberate. On POSIX, OSError(errno, strerror, filename,
    # filename2) puts the fourth argument in winerror and leaves filename2 as None;
    # filename2 only lands when the winerror slot is passed too. Measured on python3.12.
    import generate_logic_policy as g

    def line(exc):
        return _failure_line(g.failure_marker(exc, [g.PROMPT_OUT]))

    tmp = str(g.ROOT / "policy" / "logic-policy.dl.tmp")
    final = str(g.ROOT / "policy" / "logic-policy.dl")
    both = line(OSError(21, "Is a directory", tmp, None, final))
    assert str(g.ROOT) not in both, both
    assert "[Errno 21] Is a directory" in both, both
    assert "policy/logic-policy.dl.tmp" in both and "policy/logic-policy.dl'" in both, both

    # A path outside the KB has no relative form, so it keeps its basename only.
    outside = line(OSError(21, "Is a directory", "/somewhere/else/donor.dl", None, final))
    assert "/somewhere/else" not in outside, outside
    assert "donor.dl" in outside and "policy/logic-policy.dl" in outside, outside

    # No second filename: one name, and no dangling arrow suggesting a lost one.
    single = line(OSError(21, "Is a directory", str(g.ROOT / "runs" / TRACE)))
    assert f"runs/{TRACE}" in single and "->" not in single, single

    # No filename at all: nothing to rebuild from, so the message stands as written.
    assert line(OSError("boom")) == "OSError: boom"
