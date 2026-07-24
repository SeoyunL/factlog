# SPDX-License-Identifier: Apache-2.0
"""The logic report names the policy sources it actually loaded (#506).

Before this, the ``policy:`` header line was assembled from the LOGIC_POLICY_DL
constant alone, so a KB with no compiled ``policy/logic-policy.dl`` at all still
claimed ``policy: policy/logic-policy.dl`` — pointing at a file that is not on
disk — and then reported ``policy findings: 0`` as if a policy had been applied
and found nothing. Measured before the fix: a KB with no policy files and a KB
with a real (rule-less, #491) policy produced BYTE-IDENTICAL reports, so no
reader could tell "checked against a policy, nothing matched" from "checked
against nothing".

These are end-to-end pins driven through the real tools: ``factlog init`` builds
a KB, ``compile_facts`` writes engine input, ``run_logic_check`` writes the
report. That path runs wirelog, so without pyrewire there is no report to assert
on and the module skips.

What is deliberately NOT changed here, and is pinned as unchanged:
  * #190's tolerance — an absent ``.md`` is still an empty policy, rc 0.
  * #491's rule-less policy — a stub ``.dl`` is a normal, warning-free KB and
    keeps today's ``- no generated policy predicates`` wording verbatim.
  * #336's exit-code contract — none of these states changes rc.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("pyrewire", reason="run_logic_check needs the engine to write a report")

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPILE = REPO_ROOT / "tools" / "compile_facts.py"
CHECK = REPO_ROOT / "tools" / "run_logic_check.py"
HEADER = "subject,relation,object,source,status,confidence,note"
CANDIDATES = 'A,uses,B,sources/a.md,confirmed,0.90,\n'
QUERY = 'relation("A", "uses", "B")?\n'

PROSE_MD = "# Logic policy\n\nWrite rules like `- [c1] ... ` here later.\n"
STUB_DL = "// no policy rules\n"
RULE_DL = (
    ".decl requires_review(entity: symbol, reason: symbol)\n"
    'requires_review(X, "probe") :- relation(X, "uses", _).\n'
)
EXTRA_RULE_DL = (
    ".decl probe_pred(entity: symbol, reason: symbol)\n"
    'probe_pred(X, "probe") :- relation(X, "uses", _).\n'
)


def _env(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    # tools/*.py import their sibling ``common`` via sys.path[0], but
    # compile_facts imports ``factlog.common`` — put the repo root ahead of any
    # editable install pointing elsewhere.
    env["PYTHONPATH"] = os.pathsep.join([str(REPO_ROOT), env.get("PYTHONPATH", "")]).rstrip(
        os.pathsep
    )
    env["FACTLOG_ROOT"] = str(root)
    return env


def _new_kb(tmp_path: Path, name: str) -> Path:
    kb = tmp_path / name
    subprocess.run(
        [sys.executable, "-m", "factlog", "init", "--target", str(kb)],
        check=True,
        capture_output=True,
        env=_env(tmp_path),
    )
    (kb / "sources" / "a.md").write_text("a\n", encoding="utf-8")
    (kb / "facts" / "candidates.csv").write_text(f"{HEADER}\n{CANDIDATES}", encoding="utf-8")
    (kb / "facts" / "query.dl").write_text(QUERY, encoding="utf-8")
    return kb


def _policy_files(kb: Path, *, md: str | None, dl: str | None, extra: str | None) -> None:
    policy = kb / "policy"
    for name, text in (
        ("logic-policy.md", md),
        ("logic-policy.dl", dl),
        ("logic-policy.extra.dl", extra),
    ):
        path = policy / name
        if text is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(text, encoding="utf-8")


def _run_check(kb: Path) -> subprocess.CompletedProcess[str]:
    subprocess.run(
        [sys.executable, str(COMPILE)],
        cwd=kb,
        check=True,
        capture_output=True,
        env=_env(kb),
    )
    return subprocess.run(
        [sys.executable, str(CHECK)],
        cwd=kb,
        capture_output=True,
        text=True,
        env=_env(kb),
    )


def _report(kb: Path) -> str:
    return (kb / "facts" / "logic_report.txt").read_text(encoding="utf-8")


def _line(report: str, prefix: str) -> str:
    """The single report line starting with ``prefix``, whole and unabridged.

    Callers compare the WHOLE line, never a substring: a mutant that drops the
    ``(policy/logic-policy.dl absent)`` clause still satisfies an ``in`` check
    for ``policy: none``.
    """
    matches = [line for line in report.splitlines() if line.startswith(prefix)]
    assert len(matches) == 1, f"expected exactly one {prefix!r} line, got {matches!r}"
    return matches[0]


def _evaluation_block(report: str) -> list[str]:
    lines = report.splitlines()
    start = lines.index("Policy evaluation:")
    block: list[str] = []
    for line in lines[start + 1 :]:
        if not line:
            break
        block.append(line)
    return block


def _kb_in_state(
    tmp_path: Path,
    name: str,
    *,
    md: str | None,
    dl: str | None,
    extra: str | None = None,
) -> tuple[Path, subprocess.CompletedProcess[str]]:
    kb = _new_kb(tmp_path, name)
    _policy_files(kb, md=md, dl=dl, extra=extra)
    return kb, _run_check(kb)


class TestPolicyProvenanceLine:
    def test_report_policy_line_absent_no_md(self, tmp_path):
        # State A: no logic-policy.md, no logic-policy.dl. Nothing was loaded,
        # so the report must not name a file that is not there.
        kb, result = _kb_in_state(tmp_path, "kb_a", md=None, dl=None)
        assert result.returncode == 0, result.stdout + result.stderr
        assert _line(_report(kb), "policy:") == "policy: none (policy/logic-policy.dl absent)"

    def test_report_policy_line_absent_prose_md(self, tmp_path):
        # State B: a fresh `init`ed KB — prose .md, still no compiled .dl. The
        # loaded policy is empty exactly as in state A (#190), so the line says
        # the same thing: the .md is not a program the engine ran.
        kb, result = _kb_in_state(tmp_path, "kb_b", md=PROSE_MD, dl=None)
        assert result.returncode == 0, result.stdout + result.stderr
        assert _line(_report(kb), "policy:") == "policy: none (policy/logic-policy.dl absent)"

    def test_report_policy_line_empty_stub_dl_unchanged(self, tmp_path):
        # State C (#491): a compiled but rule-less policy. This is a NORMAL KB —
        # the .dl is on disk and was loaded — so every byte of today's report
        # shape survives: the plain path, no warning, rc 0.
        kb, result = _kb_in_state(tmp_path, "kb_c", md=PROSE_MD, dl=STUB_DL)
        report = _report(kb)
        assert result.returncode == 0, result.stdout + result.stderr
        assert _line(report, "policy:") == "policy: policy/logic-policy.dl"
        assert _line(report, "warnings:") == "warnings: 0"
        assert _line(report, "errors:") == "errors: 0"
        assert _evaluation_block(report) == ["- no generated policy predicates"]

    def test_report_policy_line_compiled_rules(self, tmp_path):
        # State D: the ordinary case. Unchanged, and pinned so a provenance bug
        # cannot start decorating the line every KB shows.
        kb, result = _kb_in_state(tmp_path, "kb_d", md=PROSE_MD, dl=RULE_DL)
        report = _report(kb)
        assert result.returncode == 0, result.stdout + result.stderr
        assert _line(report, "policy:") == "policy: policy/logic-policy.dl"
        assert _evaluation_block(report) == ["- requires_review: 1 rows"]

    def test_report_policy_line_extra_dl_only(self, tmp_path):
        # The trap: with no compiled .dl a hand-authored logic-policy.extra.dl
        # (#120) still reaches the engine, and its predicates ARE evaluated.
        # Saying "none" here would be the same class of lie #506 removes.
        kb, result = _kb_in_state(tmp_path, "kb_extra", md=PROSE_MD, dl=None, extra=EXTRA_RULE_DL)
        report = _report(kb)
        assert result.returncode == 0, result.stdout + result.stderr
        assert _line(report, "policy:") == (
            "policy: policy/logic-policy.extra.dl (policy/logic-policy.dl absent)"
        )
        assert _evaluation_block(report) == ["- probe_pred: 1 rows"]

    def test_report_policy_line_base_and_extra(self, tmp_path):
        # Both files contribute → both are named, base first. The order is fixed
        # by the loader's own merge order, not by directory iteration.
        kb, result = _kb_in_state(
            tmp_path, "kb_both", md=PROSE_MD, dl=RULE_DL, extra=EXTRA_RULE_DL
        )
        report = _report(kb)
        assert result.returncode == 0, result.stdout + result.stderr
        assert _line(report, "policy:") == (
            "policy: policy/logic-policy.dl, policy/logic-policy.extra.dl"
        )

    def test_report_policy_line_extra_dl_comment_only_not_credited(self, tmp_path):
        # A comment-only extra.dl contributes no bytes to the engine program
        # (the loader skips `//` and `#` lines), so it must not be credited as a
        # loaded source either — otherwise the report claims a policy ran when
        # the engine saw an empty program.
        kb, result = _kb_in_state(
            tmp_path,
            "kb_extra_comments",
            md=PROSE_MD,
            dl=None,
            extra="// nothing here\n# not here either\n",
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert _line(_report(kb), "policy:") == "policy: none (policy/logic-policy.dl absent)"


class TestPolicyEvaluationBlock:
    def test_policy_evaluation_absent_policy_says_no_policy_loaded(self, tmp_path):
        # Second, independent statement of the same fact, for a reader who only
        # sees the tail of the report. It is a statement, not a warning: no new
        # section, no warnings/errors count change, no rc change (#336).
        kb, result = _kb_in_state(tmp_path, "kb_a2", md=None, dl=None)
        report = _report(kb)
        assert result.returncode == 0, result.stdout + result.stderr
        assert _evaluation_block(report) == [
            "- no policy loaded (policy/logic-policy.dl absent)"
        ]
        assert _line(report, "warnings:") == "warnings: 0"
        assert _line(report, "errors:") == "errors: 0"
        assert _line(report, "policy findings:") == "policy findings: 0"

    def test_policy_evaluation_extra_dl_only_is_not_no_policy_loaded(self, tmp_path):
        # extra.dl alone IS a loaded policy: the tail must not say otherwise.
        kb, result = _kb_in_state(
            tmp_path, "kb_extra2", md=PROSE_MD, dl=None, extra=EXTRA_RULE_DL
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert _evaluation_block(_report(kb)) == ["- probe_pred: 1 rows"]


class TestAbsentPolicyIsDistinguishable:
    def test_absent_policy_report_differs_from_empty_stub_report(self, tmp_path):
        # The assertion that closes #506: "no policy at all" and "a real policy
        # with no rules" (#491) used to write byte-identical reports.
        kb_absent, absent = _kb_in_state(tmp_path, "kb_absent", md=None, dl=None)
        kb_stub, stub = _kb_in_state(tmp_path, "kb_stub", md=PROSE_MD, dl=STUB_DL)
        assert absent.returncode == 0, absent.stdout + absent.stderr
        assert stub.returncode == 0, stub.stdout + stub.stderr
        absent_bytes = (kb_absent / "facts" / "logic_report.txt").read_bytes()
        stub_bytes = (kb_stub / "facts" / "logic_report.txt").read_bytes()
        assert absent_bytes != stub_bytes
