# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the structured doctor diagnostics (#180).

These exercise ``_collect_doctor_checks`` directly, monkeypatching the
environment so we can assert individual severities without shelling out or
touching the real machine. The contract that matters for exit codes: only
``FAIL`` rows may flip the doctor result — ``INFO``/``WARN`` are advisory.
"""
from __future__ import annotations

import collections
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import factlog.cli as cli

_REPO_ROOT = Path(__file__).resolve().parents[2]

# A stand-in for sys.version_info that supports both attribute access
# (.major/.minor, used in the f-string) and slicing (used in the comparison).
_VersionInfo = collections.namedtuple("_VersionInfo", "major minor micro releaselevel serial")


def _by_title(checks, needle):
    """Return the first check whose title contains *needle* (or None)."""
    for c in checks:
        if needle in c.title:
            return c
    return None


class TestGitCheck:
    def test_missing_git_is_fail(self, monkeypatch):
        # `shutil` is imported inside the function, so patch the module directly.
        monkeypatch.setattr(shutil, "which", lambda name: None)
        checks = cli._collect_doctor_checks()
        git = _by_title(checks, "git")
        assert git is not None
        assert git.severity == "FAIL"
        assert git.hints, "a missing-git FAIL must carry an install hint"
        # git FAIL must not gate setup — setup does no git work.
        assert git.blocks_setup is False

    def test_present_git_is_ok(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/git")
        checks = cli._collect_doctor_checks()
        git = _by_title(checks, "git")
        assert git is not None
        assert git.severity == "OK"


class TestFactlogPython:
    def test_unset_is_info(self, monkeypatch):
        monkeypatch.delenv("FACTLOG_PYTHON", raising=False)
        checks = cli._collect_doctor_checks()
        row = _by_title(checks, "FACTLOG_PYTHON")
        assert row is not None
        assert row.severity == "INFO"

    def test_set_and_existing_is_ok(self, monkeypatch, tmp_path):
        target = tmp_path / "python3"
        target.write_text("#!/bin/sh\n")
        monkeypatch.setenv("FACTLOG_PYTHON", str(target))
        checks = cli._collect_doctor_checks()
        row = _by_title(checks, "FACTLOG_PYTHON")
        assert row is not None
        assert row.severity == "OK"

    def test_set_but_missing_is_warn(self, monkeypatch, tmp_path):
        missing = tmp_path / "nope" / "python3"
        monkeypatch.setenv("FACTLOG_PYTHON", str(missing))
        checks = cli._collect_doctor_checks()
        row = _by_title(checks, "FACTLOG_PYTHON")
        assert row is not None
        assert row.severity == "WARN"


class TestShadowFolder:
    def test_shadow_folder_triggers_warn(self, monkeypatch, tmp_path):
        # A cwd with a stray ./factlog dir, no pyproject.toml, that is not the
        # real package → WARN.
        (tmp_path / "factlog").mkdir()
        monkeypatch.chdir(tmp_path)
        checks = cli._collect_doctor_checks()
        shadow = next((c for c in checks if "factlog/ 폴더" in c.title), None)
        assert shadow is not None
        assert shadow.severity == "WARN"

    def test_repo_root_does_not_trigger(self, monkeypatch, tmp_path):
        # cwd has ./factlog but also a pyproject.toml → it's the repo, not a
        # shadow. Must not fire (mirrors smoke.sh/setup.sh running from repo root).
        (tmp_path / "factlog").mkdir()
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        monkeypatch.chdir(tmp_path)
        checks = cli._collect_doctor_checks()
        assert not any("factlog/ 폴더" in c.title for c in checks)

    def test_no_factlog_folder_does_not_trigger(self, monkeypatch, tmp_path):
        # Empty cwd (mirrors the pip-install test's throwaway tmp dir).
        monkeypatch.chdir(tmp_path)
        checks = cli._collect_doctor_checks()
        assert not any("factlog/ 폴더" in c.title for c in checks)


class TestPythonSurface:
    def test_python_token_and_interpreter_path_present(self):
        checks = cli._collect_doctor_checks()
        row = _by_title(checks, "Python")
        assert row is not None
        # The interpreter path is surfaced in the title (issue #180 diag 2).
        assert cli.sys.executable in row.title

    def test_python_below_floor_is_fail(self, monkeypatch):
        monkeypatch.setattr(cli.sys, "version_info", _VersionInfo(3, 10, 0, "final", 0))
        checks = cli._collect_doctor_checks()
        row = _by_title(checks, "Python")
        assert row is not None
        assert row.severity == "FAIL"
        # And this FAIL *does* gate setup (default), unlike git.
        assert row.blocks_setup is True

    def test_windowsapps_store_stub_is_warn(self, monkeypatch):
        # Force a supported version so we reach the interpreter-surface branch,
        # then point the interpreter at a Store-stub path.
        monkeypatch.setattr(cli.sys, "version_info", _VersionInfo(3, 12, 0, "final", 0))
        monkeypatch.setattr(
            cli.sys, "executable",
            r"C:\Users\me\AppData\Local\Microsoft\WindowsApps\python.exe",
        )
        checks = cli._collect_doctor_checks()
        row = _by_title(checks, "Python")
        assert row is not None
        assert row.severity == "WARN"


class TestRenderAndExitContract:
    def test_render_returns_true_when_no_fail(self):
        checks = [
            cli.Check("OK", "Python 3.12 (/x)"),
            cli.Check("INFO", "FACTLOG_PYTHON 미설정"),
            cli.Check("WARN", "something advisory"),
        ]
        assert cli._render_doctor(checks, emit_summary=True) is True

    def test_render_returns_false_when_any_fail(self):
        checks = [cli.Check("OK", "Python 3.12 (/x)"), cli.Check("FAIL", "git이 없습니다")]
        assert cli._render_doctor(checks, emit_summary=False) is False

    def test_summary_banner_only_with_emit(self, capsys):
        cli._render_doctor([cli.Check("OK", "ok")], emit_summary=False)
        assert "결과:" not in capsys.readouterr().out
        cli._render_doctor([cli.Check("OK", "ok")], emit_summary=True)
        assert "결과:" in capsys.readouterr().out


class TestSetupGateDecoupledFromGit:
    """A missing git is reported by doctor but must not fail `factlog setup`."""

    def test_git_fail_blocks_doctor_but_not_setup(self, monkeypatch, tmp_path):
        # Healthy except for git: git absent, no shadow folder, FACTLOG_PYTHON unset.
        monkeypatch.setattr(shutil, "which", lambda name: None)
        monkeypatch.delenv("FACTLOG_PYTHON", raising=False)
        monkeypatch.chdir(tmp_path)
        checks = cli._collect_doctor_checks()

        git = _by_title(checks, "git")
        assert git is not None and git.severity == "FAIL"

        # doctor gate (all FAIL) → blocked.
        assert cli._render_doctor(checks, gate="all") is False
        # setup gate (blocks_setup FAIL only) → not blocked by git alone.
        # (pyrewire may be absent in the runner; only assert git does not gate.)
        non_git_fail = any(
            c.severity == "FAIL" and c.blocks_setup for c in checks
        )
        assert cli._render_doctor(checks, gate="setup") is (not non_git_fail)

    def test_only_git_fail_setup_gate_passes(self):
        # Synthetic check set: everything OK except a non-blocking git FAIL.
        checks = [
            cli.Check("OK", "Python 3.12 (/x)"),
            cli.Check("OK", "pyrewire 1.0.3"),
            cli.Check("FAIL", "git이 없습니다", ("hint",), blocks_setup=False),
            cli.Check("INFO", "FACTLOG_PYTHON 미설정"),
        ]
        assert cli._render_doctor(checks, gate="all") is False
        assert cli._render_doctor(checks, gate="setup") is True

    def test_blocking_fail_gates_setup(self):
        checks = [
            cli.Check("FAIL", "pyrewire not installed", ("hint",)),  # blocks_setup default True
            cli.Check("OK", "git"),
        ]
        assert cli._render_doctor(checks, gate="setup") is False


class TestHealthyEnvExitZero:
    """End-to-end: a healthy environment yields a passing (exit 0) doctor."""

    def test_healthy_env_render_returns_true(self, monkeypatch, tmp_path):
        pytest.importorskip("pyrewire")  # needed for a genuinely clean env
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/git")
        monkeypatch.delenv("FACTLOG_PYTHON", raising=False)
        monkeypatch.chdir(tmp_path)  # empty cwd: no shadow ./factlog folder
        assert cli._render_doctor(cli._collect_doctor_checks(), emit_summary=True) is True


class TestAsciiLocaleDoesNotCrash:
    """doctor must never crash on an ASCII/C-locale stdout (#180 review)."""

    def test_render_survives_ascii_stdout(self, monkeypatch):
        # A real ascii-encoded text stream: without _harden_stdout the em-dash /
        # Korean in the banner would raise UnicodeEncodeError here.
        import io

        buf = io.BytesIO()
        ascii_stdout = io.TextIOWrapper(buf, encoding="ascii", newline="")
        monkeypatch.setattr(cli.sys, "stdout", ascii_stdout)
        cli._render_doctor([cli.Check("OK", "Python 3.12 (/x)")], emit_summary=True)
        ascii_stdout.flush()
        out = buf.getvalue().decode("ascii")
        assert "Python" in out  # ASCII token still comes through
        # Non-ASCII degraded to backslash escapes rather than crashing.
        assert "\\u" in out or "\\x" in out

    def test_doctor_subprocess_under_c_locale(self, tmp_path):
        pytest.importorskip("pyrewire")
        if shutil.which("git") is None:
            pytest.skip("git required to assert a clean exit 0")
        env = dict(
            os.environ,
            LC_ALL="C",
            LANG="C",
            LANGUAGE="C",
            PYTHONIOENCODING="ascii",
        )
        env.pop("FACTLOG_PYTHON", None)
        # Run from the repo root so `-m factlog` resolves without an install,
        # and pyproject.toml there suppresses the shadow-folder heuristic.
        proc = subprocess.run(
            [sys.executable, "-m", "factlog", "doctor"],
            cwd=str(_REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
        )
        combined = proc.stdout + proc.stderr
        assert "Traceback" not in combined, combined
        assert "UnicodeEncodeError" not in combined, combined
        assert "Python" in combined, combined
        assert proc.returncode == 0, combined
