# SPDX-License-Identifier: Apache-2.0
"""The policy loader reports which files it loaded, and nothing else changes (#506).

``tools/run_logic_check.py`` has to name the policy sources it checked against, and
"did ``logic-policy.extra.dl`` contribute?" is a non-obvious rule owned by the loader
(non-empty, and at least one line that is neither ``//`` nor ``#``). Re-deriving it in
the reporter would add a fifth policy parser to drift away from this one (#226/#250/
#333), so the loader answers it: ``LogicPolicyProgram`` carries the text plus the
files whose bytes reached it, in merge order.

The point of these tests is that the provenance is a pure addition: the ENGINE PROGRAM
TEXT is byte-identical to what ``_load_logic_policy_from`` returned before, in every
policy shape, and the loud paths (#190's uncompiled rules) still raise. No engine is
needed — the loader is plain file reading.
"""
from __future__ import annotations

import pytest

import run_logic_check as rlc
from factlog import common

PROSE_MD = "# Logic policy\n\nWrite rules like `- [c1] ... ` here later.\n"
RULES_MD = "# Logic policy\n\n- [c1] flag when `requires_review`\n"
STUB_DL = "// no policy rules\n"
BASE_DL = ".decl requires_review(entity: symbol, reason: symbol)\n"
EXTRA_DL = ".decl after2030(entity: symbol, reason: symbol)\n"
COMMENT_EXTRA_DL = "// nothing here\n# not here either\n\n"


def _policy(tmp_path, *, md=None, dl=None, extra=None):
    policy = tmp_path / "policy"
    policy.mkdir(parents=True, exist_ok=True)
    for name, text in (
        ("logic-policy.md", md),
        ("logic-policy.dl", dl),
        ("logic-policy.extra.dl", extra),
    ):
        if text is not None:
            (policy / name).write_text(text, encoding="utf-8")
    return policy / "logic-policy.dl"


class TestLoadedSources:
    def test_no_md_no_dl_loads_nothing(self, tmp_path):
        dl = _policy(tmp_path)
        program = common._load_logic_policy_program_from(dl)
        assert program.sources == ()
        assert program.base_loaded is False
        assert program.base == dl

    def test_prose_md_no_dl_loads_nothing(self, tmp_path):
        dl = _policy(tmp_path, md=PROSE_MD)
        program = common._load_logic_policy_program_from(dl)
        assert program.sources == ()
        assert program.base_loaded is False

    def test_stub_dl_is_a_loaded_source(self, tmp_path):
        # #491: a compiled policy with no rules IS a policy. Presence, not content.
        dl = _policy(tmp_path, md=PROSE_MD, dl=STUB_DL)
        program = common._load_logic_policy_program_from(dl)
        assert program.sources == (dl,)
        assert program.base_loaded is True

    def test_compiled_dl_is_a_loaded_source(self, tmp_path):
        dl = _policy(tmp_path, md=PROSE_MD, dl=BASE_DL)
        program = common._load_logic_policy_program_from(dl)
        assert program.sources == (dl,)

    def test_base_and_extra_are_listed_in_merge_order(self, tmp_path):
        dl = _policy(tmp_path, md=PROSE_MD, dl=BASE_DL, extra=EXTRA_DL)
        program = common._load_logic_policy_program_from(dl)
        assert program.sources == (dl, dl.with_name("logic-policy.extra.dl"))

    def test_extra_alone_is_a_loaded_source(self, tmp_path):
        # #120: no compiled .dl, but the hand-authored sibling reaches the engine.
        # "The base is missing" must not be read as "no policy was applied".
        dl = _policy(tmp_path, md=PROSE_MD, extra=EXTRA_DL)
        program = common._load_logic_policy_program_from(dl)
        assert program.sources == (dl.with_name("logic-policy.extra.dl"),)
        assert program.base_loaded is False

    def test_comment_only_extra_is_not_credited(self, tmp_path):
        # Contributes no bytes to the program, so it is not a loaded source —
        # exactly the rule the merge tail applies to `//` and `#` lines.
        dl = _policy(tmp_path, md=PROSE_MD, extra=COMMENT_EXTRA_DL)
        program = common._load_logic_policy_program_from(dl)
        assert program.sources == ()

    def test_comment_only_extra_does_not_hide_the_base(self, tmp_path):
        dl = _policy(tmp_path, md=PROSE_MD, dl=BASE_DL, extra=COMMENT_EXTRA_DL)
        program = common._load_logic_policy_program_from(dl)
        assert program.sources == (dl,)


class TestProgramTextUnchanged:
    """Provenance is bookkeeping: the text handed to the engine must not move."""

    @pytest.mark.parametrize(
        "files, expected",
        [
            ({}, ""),
            ({"md": PROSE_MD}, ""),
            ({"md": PROSE_MD, "dl": STUB_DL}, STUB_DL.strip()),
            ({"md": PROSE_MD, "dl": BASE_DL}, BASE_DL.strip()),
            (
                {"md": PROSE_MD, "dl": BASE_DL, "extra": EXTRA_DL},
                BASE_DL.strip() + "\n" + EXTRA_DL.strip(),
            ),
            # No leading newline when the base is empty (#116 invariant 1).
            ({"md": PROSE_MD, "extra": EXTRA_DL}, EXTRA_DL.strip()),
            ({"md": PROSE_MD, "extra": COMMENT_EXTRA_DL}, ""),
            ({"md": PROSE_MD, "dl": BASE_DL, "extra": COMMENT_EXTRA_DL}, BASE_DL.strip()),
        ],
    )
    def test_text_matches_the_pre_provenance_loader(self, tmp_path, files, expected):
        dl = _policy(tmp_path, **files)
        assert common._load_logic_policy_from(dl) == expected
        assert common._load_logic_policy_program_from(dl).text == expected


class TestReportLinesAgreeOnWhatLoaded:
    """The header and the tail must never contradict each other (#506 review).

    ``policy_provenance_line`` and ``policy_evaluation_default`` both answer "was a
    policy applied here", and while they answered it with two different expressions
    a KB whose only policy is a contributing extra.dl got a header naming that file
    over a tail saying no policy was loaded — the #506 lie pointing the other way.
    Both now read ``LogicPolicyProgram.loaded``; these pin the pair.

    Engine-free by design, and they live in this module for that reason: the seam is
    two pure renderers over a loader value, so it must stay pinned on a machine with
    no pyrewire. The programs come from the REAL loader over real files so the
    fixtures cannot drift from what it actually returns; only the rendering is
    called directly, which is what lets the ruleless case be reached without
    depending on how a given engine build declares predicates.
    """

    @pytest.mark.parametrize(
        "files, expected_header, expected_tail",
        [
            # Nothing on disk: both lines say so, and the tail names the file a
            # reader would go looking for.
            (
                {"md": PROSE_MD},
                "policy: none (policy/logic-policy.dl absent)",
                "- no policy loaded (policy/logic-policy.dl absent)",
            ),
            # A compiled policy with no rules (#491): loaded, so the tail keeps
            # today's wording.
            (
                {"md": PROSE_MD, "dl": STUB_DL},
                "policy: policy/logic-policy.dl",
                "- no generated policy predicates",
            ),
            # The divergence that survived: no compiled .dl, but a contributing
            # extra.dl (#120). A policy WAS loaded — the tail must not deny it.
            (
                {"md": PROSE_MD, "extra": EXTRA_DL},
                "policy: policy/logic-policy.extra.dl (policy/logic-policy.dl absent)",
                "- no generated policy predicates",
            ),
            # A comment-only extra.dl contributes nothing, so this is the
            # nothing-loaded case again, not the one above.
            (
                {"md": PROSE_MD, "extra": COMMENT_EXTRA_DL},
                "policy: none (policy/logic-policy.dl absent)",
                "- no policy loaded (policy/logic-policy.dl absent)",
            ),
            (
                {"md": PROSE_MD, "dl": BASE_DL, "extra": EXTRA_DL},
                "policy: policy/logic-policy.dl, policy/logic-policy.extra.dl",
                "- no generated policy predicates",
            ),
        ],
    )
    def test_header_and_tail_report_the_same_load(
        self, tmp_path, files, expected_header, expected_tail
    ):
        program = common._load_logic_policy_program_from(_policy(tmp_path, **files))
        assert rlc.policy_provenance_line(program) == expected_header
        assert rlc.policy_evaluation_default(program) == expected_tail

    def test_extra_only_policy_is_never_reported_as_no_policy_loaded(self, tmp_path):
        # Stated once more on its own, because this is the shape that had no
        # coverage: sources non-empty while the base is absent. A tail keyed on
        # "was the BASE loaded" answers "no policy loaded" here and is wrong.
        program = common._load_logic_policy_program_from(
            _policy(tmp_path, md=PROSE_MD, extra=EXTRA_DL)
        )
        assert program.loaded is True
        assert program.base_loaded is False
        assert "no policy loaded" not in rlc.policy_evaluation_default(program)


class TestLoudPathsUnchanged:
    def test_rules_md_without_dl_still_raises_from_both_entry_points(self, tmp_path):
        # #190: rules written but never compiled is still a loud error. The
        # provenance sibling must not soften it into "policy: none".
        dl = _policy(tmp_path, md=RULES_MD)
        with pytest.raises(common.FactlogError):
            common._load_logic_policy_from(dl)
        with pytest.raises(common.FactlogError):
            common._load_logic_policy_program_from(dl)

    def test_canonical_head_guard_still_fires(self, tmp_path):
        dl = _policy(tmp_path, md=PROSE_MD, dl='canonical(X, "y") :- relation(X, "uses", _).\n')
        with pytest.raises(common.FactlogError):
            common._load_logic_policy_program_from(dl)
