# SPDX-License-Identifier: Apache-2.0
"""Every .decl parser must read the directive the way the ENGINE reads it (#508).

`.decl p (entity: symbol, reason: symbol)` — one space before the paren — is a
declaration pyrewire accepts and derives rows for. factlog's own parsers did not
see it: `policy_predicates` returned an empty set, so `run_logic_check` never
queried the predicate and the report said `policy findings: 0` for a policy that
had in fact fired. "I verified and nothing was found" is the one sentence this KB
may never say falsely, and it said it over a space.

The same space tore BOTH typed-alias collision nets at once: the parse-time net
names the policy's predicates through `policy_predicates`, and the assembly-time
net had its own equally narrow regex, so a KB could ship a program declaring
`pub_year` twice with different arities, compile rc=0, and quietly derive
different rows.

Six regexes read `.decl` three different ways in factlog/common.py. They now
share one name grammar and split along ONE axis: readers of a comment-stripped
skeleton use `_DECL_RE` (and its column/strip variants), readers of raw text use
the anchored `_DECL_LINE_RE`. The sixth, the reserved-head guard, is deliberately
wider than both and stays that way. These tests pin the agreement, the intentional
gap, and the residual one — because the failure mode of this module is not a
crash, it is silence.

Since #516 the raw side has ONE member, `_engine_decl_predicates`. The
assembly-time alias net moved to the skeleton because its raw blind spot is one
the engine accepts AS A DECLARATION and the skeleton's blind spot is one the
engine ParseErrors on — measured both ways below, since that asymmetry is the
entire argument and it would rot silently if pyrewire changed.

Measured against pyrewire 1.0.3 (TestEngineAcceptsTheseForms below re-measures
it, so the day the engine narrows, the reason for widening these parsers is
gone and a test says so).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import factlog.common as fcommon

REPO_ROOT = Path(__file__).resolve().parents[2]

COLS = "entity: symbol, reason: symbol"


def form(template: str, name: str = "p", cols: str = COLS) -> str:
    """Render one declaration form for *name*.

    Templates rather than fixed text with `.replace(".decl p", ...)`: a replace
    that matches nothing leaves the original string and the test then asserts
    against a predicate it never declared — it passes or fails for a reason that
    has nothing to do with the code. Two of the forms below have no literal
    `.decl p` in them at all.
    """
    return template.format(name=name, cols=cols)


# Every way of writing ONE declaration that the engine accepts. The NAME is held
# fixed here and varied in NAME_FORMS, so neither axis can hide a narrowing in
# the other.
WHITESPACE_FORMS = {
    "tight": ".decl {name}({cols})\n",
    "one space": ".decl {name} ({cols})\n",
    "tab": ".decl {name}\t({cols})\n",
    "newline": ".decl {name}\n({cols})\n",
    "blank line": ".decl {name}\n\n({cols})\n",
    "indented": "  .decl {name}({cols})\n",
    "indented and spaced": "  .decl {name} ({cols})\n",
    "tab-indented": "\t.decl {name} ({cols})\n",
}

# Forms the engine also accepts, and that only a COMMENT-STRIPPING reader resolves.
# The rule is ONE proposition, not a list of curiosities: the raw-text site sees a
# `.decl` only when it OPENS ITS LINE and NO COMMENT falls anywhere inside the
# directive — not between `.decl` and the name, and not between the name and the
# paren. Everything below violates one conjunct or the other. (An earlier wording
# said only "name and paren not split", which its own third entry refutes: there
# the `.decl` opens the line and the name touches its paren, and the raw reader
# still misses it because the comment sits between `.decl` and the name.)
#
# WHOSE gap this is changed in #516 and the list did not: measured, all five are
# still invisible to `_DECL_LINE_RE`. What moved is the other side. It used to be
# net 1 (skeleton) against net 2 (raw); now three skeleton readers —
# policy_predicates, the column guard, and `_assert_no_alias_collision` — stand
# against the ONE raw reader left, `_engine_decl_predicates`. See
# TestTheLastRawTextSiteCannotStripComments.
#
# "new" / "pre-existing" is measured against the state before #508, per form —
# #508 did not create them all. Widening only the skeleton readers split the two
# comment-SPLIT forms, which were missed on both sides before; the not-line-initial
# forms already diverged because their paren touches the name.
#
# This dict is a SINGLE POINT for three parametrized tests: deleting an entry drops
# a case from
# TestPolicyPredicatesSeesEveryWhitespaceForm::test_comment_stripped_forms_are_visible_too
# and from both methods of TestTheLastRawTextSiteCannotStripComments at once, with
# nothing turning red. Add here, do not narrow here.
SKELETON_ONLY_FORMS = {
    # new (#508): main's skeleton regex needed the paren to touch the name, so it
    # missed these too, and the two readers were blind together.
    "comment between name and paren": ".decl {name} // why\n({cols})\n",
    "hash comment between name and paren": ".decl {name} # why\n({cols})\n",
    # pre-existing: the paren touches the name, so main's skeleton reader already
    # saw these while its `^`-anchored raw reader already did not.
    "comment between .decl and name": ".decl // why\n{name}({cols})\n",
    "second decl on the same line": ".decl other({cols}) .decl {name}({cols})\n",
    "after a rule on the same line": 'q(X, Y) :- relation(X, "a", Y). .decl {name}({cols})\n',
}

# Names the engine accepts (measured). Kept separate from the whitespace matrix so
# a site whose character class narrows cannot hide behind an all-lower-case table.
NAME_FORMS = {
    "lower": "p",
    "MixedCase": "MyPred",
    "UPPER": "PRED",
    "leading underscore": "_p",
    "trailing digit": "p2",
}


class TestPolicyPredicatesSeesEveryWhitespaceForm:
    """Consumer 1 — the one the issue is about. run_logic_check queries exactly the
    names this returns, so a name missing here is a finding missing from the report."""

    @pytest.mark.parametrize("label", sorted(WHITESPACE_FORMS))
    def test_whitespace_form_is_a_visible_predicate(self, label):
        policy = form(WHITESPACE_FORMS[label]) + 'p(X, "r") :- relation(X, "cites", _).\n'
        assert fcommon.policy_predicates(policy) == {"p"}, label

    def test_uppercase_name_is_visible(self):
        """The engine accepts MixedCase; a lower-case-only regex would drop the
        predicate entirely rather than reject the policy."""
        assert fcommon.policy_predicates(f".decl MyPred ({COLS})\n") == {"MyPred"}

    def test_two_decls_on_one_line_are_both_visible(self):
        assert fcommon.policy_predicates(f".decl p({COLS}) .decl q({COLS})\n") == {"p", "q"}

    @pytest.mark.parametrize("label", sorted(SKELETON_ONLY_FORMS))
    def test_comment_stripped_forms_are_visible_too(self, label):
        assert "p" in fcommon.policy_predicates(form(SKELETON_ONLY_FORMS[label])), label

    def test_comment_is_still_not_a_declaration(self):
        """Widening the whitespace must not widen what counts as CODE. A policy
        author comments a predicate out to disable it; if the report then listed it
        as a finding source, the disable would be a lie in the other direction."""
        assert fcommon.policy_predicates(f"// .decl ghost({COLS})\n") == set()
        assert fcommon.policy_predicates(f"# .decl ghost ({COLS})\n") == set()

    def test_string_literal_is_still_not_a_declaration(self):
        policy = (
            f".decl flag({COLS})\n"
            'flag(X, ".decl ghost (a: symbol, b: symbol)") :- relation(X, "a", _).\n'
        )
        assert fcommon.policy_predicates(policy) == {"flag"}


# --- the four sites that extract a NAME, probed through their behaviour --------
#
# Probing behaviour, not the regex objects: a test that re-implements the pattern
# it is checking passes for the same reason the code is wrong. Each helper answers
# one question — "does THIS site consider `p` declared?" — the way a caller would
# find out.


def _seen_by_policy_predicates(text: str, name: str = "p") -> bool:
    return name in fcommon.policy_predicates(text)


def _seen_by_alias_collision(text: str, name: str = "p") -> bool:
    """The assembly-time typed-alias net: it raises iff it holds *name* declared."""
    specs = {"게재연도": fcommon.TypedRelSpec("date", name)}
    try:
        fcommon._assert_no_alias_collision(specs, text)
    except fcommon.FactlogError:
        return True
    return False


def _seen_by_column_guard(text: str, name: str = "p") -> bool:
    """The arity/column-type guard: a one-column `.decl` raises iff it is seen."""
    one_column = text.replace(COLS, "entity: symbol")
    try:
        fcommon._assert_no_canonical_head(one_column)
    except fcommon.FactlogError as exc:
        assert "column" in str(exc)
        return True
    return False


@pytest.fixture
def seen_by_engine_decls(monkeypatch):
    """The reserved-predicate source of truth, over a substituted WIRELOG_PROGRAM.

    Its real input is a constant we own, so today every form gives the same answer.
    That is exactly why it is worth pinning: the four consumers of this function
    (RESERVED_PREDICATES, the typed-alias reserved set, policy_predicates' built-in
    filter, the reserved-head source table) lose a predicate SIMULTANEOUSLY and
    silently if the next line added to WIRELOG_PROGRAM is indented or MixedCase.
    #332 and #334 each shipped that accident once.
    """

    def _seen(text: str, name: str = "p") -> bool:
        monkeypatch.setattr(fcommon, "WIRELOG_PROGRAM", text)
        fcommon._engine_decl_predicates.cache_clear()
        return name in fcommon._engine_decl_predicates()

    yield _seen
    fcommon._engine_decl_predicates.cache_clear()


class TestFourNameParsersAgree:
    @pytest.mark.parametrize("label", sorted(WHITESPACE_FORMS))
    def test_all_four_sites_see_the_same_declaration(self, label, seen_by_engine_decls):
        text = form(WHITESPACE_FORMS[label])
        verdicts = {
            "policy_predicates": _seen_by_policy_predicates(text),
            "_assert_no_alias_collision": _seen_by_alias_collision(text),
            "policy column guard": _seen_by_column_guard(text),
            "_engine_decl_predicates": seen_by_engine_decls(text),
        }
        assert all(verdicts.values()), f"{label}: sites disagree — {verdicts}"

    @pytest.mark.parametrize("label", sorted(NAME_FORMS))
    def test_all_four_sites_accept_the_same_name_grammar(self, label, seen_by_engine_decls):
        """The whitespace matrix above holds the NAME fixed at `p`, so it cannot
        notice a site whose character class narrows. It has to: `[A-Za-z_]` shrunk
        to `[a-z_]` silently removes a MixedCase predicate from the reserved set and
        from the alias-collision net, not just from the report."""
        name = NAME_FORMS[label]
        text = form(WHITESPACE_FORMS["one space"], name)
        verdicts = {
            "policy_predicates": _seen_by_policy_predicates(text, name),
            "_assert_no_alias_collision": _seen_by_alias_collision(text, name),
            "policy column guard": _seen_by_column_guard(text, name),
            "_engine_decl_predicates": seen_by_engine_decls(text, name),
        }
        assert all(verdicts.values()), f"{name}: sites disagree — {verdicts}"

    @pytest.mark.parametrize("label", sorted(WHITESPACE_FORMS))
    def test_no_site_sees_a_commented_out_declaration(self, label, seen_by_engine_decls):
        """Parity in the other direction. A widened parser that starts counting
        commented-out declarations would raise a bogus alias collision and BLOCK a
        KB over a line the engine never reads."""
        text = "// " + form(WHITESPACE_FORMS[label]).replace("\n", " ") + "\n"
        verdicts = {
            "policy_predicates": _seen_by_policy_predicates(text),
            "_assert_no_alias_collision": _seen_by_alias_collision(text),
            "policy column guard": _seen_by_column_guard(text),
            "_engine_decl_predicates": seen_by_engine_decls(text),
        }
        assert not any(verdicts.values()), f"{label}: false declaration — {verdicts}"


class TestDeclRemovalKeepsTheHeadGuardIntact:
    """The `.decl`-stripping pattern is load-bearing for a DIFFERENT guard.

    After the column checks, the declarations are removed and what is left is split
    into statements so the reserved-HEAD guard can read each head. A `.decl` carries
    no clause-terminating `.`, so one left behind swallows the next rule into its
    own statement — and that statement now starts with `.decl`, which the head regex
    cannot match. The reserved head then escapes a guard whose entire job is to be
    fail-closed. Measured: with the paren tightened back onto the name,
    `canonical(X, Y) :- p(X, Y)` under a spaced `.decl` is accepted silently.
    """

    def test_reserved_head_under_a_spaced_decl_is_still_rejected(self):
        policy = ".decl p (a: symbol, b: symbol)\ncanonical(X, Y) :- p(X, Y).\n"
        with pytest.raises(fcommon.FactlogError, match="canonical"):
            fcommon._assert_no_canonical_head(policy)

    @pytest.mark.parametrize("label", sorted(WHITESPACE_FORMS))
    def test_every_whitespace_form_leaves_the_next_rule_readable(self, label):
        policy = form(WHITESPACE_FORMS[label]) + "edge(X, Y) :- relation(X, \"cites\", Y).\n"
        with pytest.raises(fcommon.FactlogError, match="edge"):
            fcommon._assert_no_canonical_head(policy)


class TestTheLastRawTextSiteCannotStripComments:
    """Where the four sites still disagree, stated as a rule and measured per form.

    Since #516, THREE sites read a _scan_policy SKELETON (comments removed, string
    literals blanked) — policy_predicates, the column guard and
    `_assert_no_alias_collision` — and exactly ONE reads RAW text:
    `_engine_decl_predicates`, over WIRELOG_PROGRAM. The raw one sees a `.decl`
    only when it OPENS ITS LINE and NO COMMENT falls anywhere inside the directive
    — between `.decl` and the name counts just as much as between the name and the
    paren. Both conjuncts are needed: `.decl // why` + newline + `p(cols)` opens
    its line and has its paren against its name, and the raw reader still does not
    see it.

    Two of the five forms in SKELETON_ONLY_FORMS are a divergence #508 CREATED:
    before it, the skeleton regex required the paren to touch the name, so both
    readers missed a comment-split `.decl` and were consistently blind. Widening
    the skeleton side alone split them. The other three already diverged. That
    history is why the gap is worth measuring rather than assuming.

    Why `_assert_no_alias_collision` moved to the skeleton in #516: the two blind
    spots are not symmetric once you ask which one a WORKING KB can reach.
    Measured, pyrewire 1.0.3 accepts all five forms below and applies the column
    schema to them, so the raw blind spot is reachable and silent — a duplicate
    `.decl` with a different arity compiles rc=0 and changes what is derived. The
    skeleton's blind spot is truncation at an unterminated string, and pyrewire
    ParseErrors on those programs, so it only covers programs that never reach a
    report. Both halves are pinned below. Performance is NOT part of this and
    should not be cited either way.

    Why the raw site is not moved too: its input is a constant we own, so today it
    would answer alike, and the anchor is what keeps a commented-out line in
    WIRELOG_PROGRAM from becoming an engine predicate. The gap it leaves is real
    all the same — the fixture below exists because the four consumers of
    `_engine_decl_predicates` lose a predicate simultaneously and silently if the
    next line added to that constant is indented or MixedCase (#332, #334).
    """

    def test_the_skeleton_stops_at_an_unterminated_string(self):
        """The truncation is real — and it is confined to programs the engine kills.

        Everything after a stray quote is gone from the skeleton, declarations
        included, so `_assert_no_alias_collision` does not see pub_year here. That
        would be a fail-open hole if such a program could reach a report; the third
        assertion is the premise that it cannot, and it is measured, not assumed.
        The narrower argument — that this net's actual input cannot even be
        truncated before a `.decl` — is in the function's docstring and pinned by
        test_accepted_dl_style_truncation_does_not_hide_a_later_decl below.
        """
        text = 'q(X, "oops) :- relation(X, "a", _).\n' + f".decl pub_year({COLS})\n"
        skeleton, _ = fcommon._scan_policy(text, strict=False)
        assert "pub_year" not in skeleton
        assert not _seen_by_alias_collision(text, "pub_year")
        if fcommon.EasySession is None:
            pytest.skip("the engine half of this claim needs pyrewire installed")
        with pytest.raises(Exception):
            fcommon.EasySession(text)

    def test_the_alias_net_does_not_raise_a_whole_program_parse_error(self):
        """strict=False, and why it may not be tightened to strict=True.

        accepted.dl is the last component of the assembled program and
        `_load_accepted_facts_from` lets a `canonical("A", "x, "B").` row through,
        so an unterminated literal CAN reach this net. With strict=True the lexer
        raises, and a targeted alias check would start reporting someone else's
        parse error — a different message, a different cause, and a KB blocked by
        the guard rather than by the compile step that owns that diagnosis.
        """
        specs = {"게재연도": fcommon.TypedRelSpec("date", "pub_year")}
        text = f".decl other({COLS})\n" + 'canonical("A", "x, "B").\n'
        with pytest.raises(fcommon.FactlogError):
            fcommon._scan_policy(text, strict=True)
        fcommon._assert_no_alias_collision(specs, text)  # does not raise

    def test_accepted_dl_style_truncation_does_not_hide_a_later_decl(self):
        """The order argument, measured rather than asserted in prose.

        The only unterminated literal that survives `_load_accepted_facts_from` is
        in accepted.dl, and run_wirelog appends accepted.dl LAST — so the policy's
        declarations are lexed before the truncation point and stay visible.
        """
        specs = {"게재연도": fcommon.TypedRelSpec("date", "pub_year")}
        assembled = f".decl pub_year({COLS})\n" + 'canonical("A", "x, "B").\n'
        with pytest.raises(fcommon.FactlogError, match="collides"):
            fcommon._assert_no_alias_collision(specs, assembled)

    @pytest.mark.parametrize("label", sorted(SKELETON_ONLY_FORMS))
    def test_the_raw_text_site_does_not_see_them(self, label, seen_by_engine_decls):
        """The gap, per form, and which side of it each reader is on now.

        `_assert_no_alias_collision` SEES all five since #516 — that assertion is
        the one that flipped, and it is what makes the move visible rather than a
        silent refactor. `_engine_decl_predicates` still does not.
        """
        text = form(SKELETON_ONLY_FORMS[label])
        assert _seen_by_alias_collision(text), label
        assert not seen_by_engine_decls(text), label

    @pytest.mark.parametrize("label", sorted(SKELETON_ONLY_FORMS))
    def test_the_parse_time_net_still_catches_the_alias_collision(self, label):
        """The consequence that would matter is still blocked."""
        policy = form(SKELETON_ONLY_FORMS[label], "pub_year")
        reserved = fcommon._typed_reserved_names(
            relations=set(), predicates=fcommon.policy_predicates(policy)
        )
        with pytest.raises(fcommon.FactlogError, match="reserved or existing"):
            fcommon._parse_typed_relations("`게재 연도` : date as pub_year\n", reserved)


class TestReservedHeadGuardIsDeliberatelyWider:
    """The sixth parser stops at the NAME and never looks for `(`.

    It is fail-closed: re-declaring an engine predicate corrupts the program with
    rc=0, so a malformed or half-typed `.decl canonical` must be rejected too.
    Folding it into the shared paren-requiring pattern for tidiness would NARROW
    it — the opposite of what #508 is for. These tests fail if that happens.
    """

    @pytest.mark.parametrize("reserved", sorted(fcommon._engine_decl_predicates()))
    def test_parenless_reserved_decl_is_rejected(self, reserved):
        with pytest.raises(fcommon.FactlogError):
            fcommon._assert_no_canonical_head(f".decl {reserved}\n")

    def test_the_other_sites_do_not_see_a_parenless_decl(self, seen_by_engine_decls):
        """The gap is real and intended, not an oversight in one direction: a
        `.decl p` with no columns declares nothing the report could render."""
        text = ".decl p\n"
        assert not _seen_by_policy_predicates(text)
        assert not _seen_by_alias_collision(text)
        assert not seen_by_engine_decls(text)

    @pytest.mark.parametrize("form", ["p ", "p\t", "p\n"])
    def test_whitespace_forms_of_a_reserved_decl_are_rejected(self, form):
        with pytest.raises(fcommon.FactlogError):
            fcommon._assert_no_canonical_head(f".decl {form.replace('p', 'canonical')}({COLS})\n")


class TestNetTwoStillExcludesComments:
    """The property #516 had to preserve while changing HOW it is obtained.

    A collision raised over a commented-out `// .decl pub_year(...)` blocks a KB
    over a line the engine never reads, so `_assert_no_alias_collision` must not
    count one. Before #516 the `^` anchor bought that exclusion by accident of
    position; now the skeleton buys it by actually removing the comment — which is
    also why the mid-line case below moved from "not at a line start" to "inside a
    string literal, and the lexer blanked it".

    These stay pinned per case rather than folded into the parity matrix: the
    exclusion is what makes this net safe to widen, and a widening that quietly
    took comments with it would fail nothing else here.
    """

    SPECS = {"게재연도": fcommon.TypedRelSpec("date", "pub_year")}

    def test_commented_decl_does_not_block_the_kb(self):
        program = (
            ".decl relation(subject: symbol, rel: symbol, object: symbol)\n"
            f"// .decl pub_year({COLS})\n"
            f"   // .decl pub_year ({COLS})\n"
        )
        fcommon._assert_no_alias_collision(self.SPECS, program)  # does not raise

    def test_mid_line_decl_does_not_block_the_kb(self):
        program = f'q(X, ".decl pub_year({COLS})") :- relation(X, "a", _).\n'
        fcommon._assert_no_alias_collision(self.SPECS, program)  # does not raise

    def test_a_real_decl_on_that_same_program_still_collides(self):
        """Control: the exclusion above is about the comment, not about the guard
        having stopped working."""
        program = (
            f"// .decl pub_year({COLS})\n"
            ".decl pub_year(subject: symbol, v: int64)\n"
        )
        with pytest.raises(fcommon.FactlogError):
            fcommon._assert_no_alias_collision(self.SPECS, program)


class TestTheAnchorOnTheLastRawSite:
    """`_DECL_LINE_RE`'s `[ \\t]*` — pinned where the pattern is still USED.

    #516 moved `_assert_no_alias_collision` to the skeleton, which left
    `_engine_decl_predicates` as the pattern's only caller. This case moved with
    it. Left on the old site it would have gone on passing for a reason that had
    nothing to do with the anchor, and `[ \\t]*` → `\\s*` would then be a change no
    test could notice.
    """

    @pytest.mark.parametrize("ws", ["\v", "\f"])
    def test_vertical_whitespace_is_not_a_line_start(self, ws, seen_by_engine_decls):
        """Why the anchor allows `[ \\t]*` and not `\\s*`: the anchor has to mean
        "this line starts here", and `\\s` matches newlines, so `^\\s*` lets the run
        cross lines and the anchor stops meaning anything. \\v/\\f are where the two
        forms actually differ (\\r cannot reach here — Path.read_text translates it
        to \\n before this text is read), so they are what pins the choice.

        NOT justified as "our parser must never be wider than the engine". The
        engine does ParseError on \\v/\\f (see TestEngineAcceptsTheseForms), but
        policy_predicates counts `\\v.decl p(...)` all the same, so that is not a
        rule this module keeps. It is harmless there — a program the engine rejects
        never reaches a report — and stating a principle the neighbouring line
        breaks would just be a new thing for someone to rely on wrongly.
        """
        program = f".decl relation(subject: symbol, rel: symbol, object: symbol)\n{ws}.decl pub_year(subject: symbol, v: int64)\n"
        assert not seen_by_engine_decls(program, "pub_year")
        assert seen_by_engine_decls(program, "relation")  # control: the scan ran


class TestTypedAliasCollisionSurvivesWhitespace:
    """The #508 second casualty: ONE space slipped past BOTH nets.

    A duplicate `.decl` is accepted by the engine with rc=0, and when the two
    declarations disagree on arity the derived rows change with no diagnostic. The
    nets are deliberately redundant, so each is pinned SEPARATELY — a fix that
    widened only one would leave the other as the surviving hole, and a test that
    only asserted "something raises" would pass on that half-fix.
    """

    ALIAS_LINE = "`게재 연도` : date as pub_year\n"

    @pytest.mark.parametrize("label", sorted(WHITESPACE_FORMS))
    def test_parse_time_net_rejects_the_alias(self, label):
        """Net 1: the alias is refused while typed-relations.md is parsed, because
        the policy already declares that name. It learns the policy's names from
        policy_predicates — the function #508 fixed."""
        policy = form(WHITESPACE_FORMS[label], "pub_year")
        reserved = fcommon._typed_reserved_names(
            relations=set(), predicates=fcommon.policy_predicates(policy)
        )
        with pytest.raises(fcommon.FactlogError, match="reserved or existing"):
            fcommon._parse_typed_relations(self.ALIAS_LINE, reserved)

    @pytest.mark.parametrize("label", sorted(WHITESPACE_FORMS))
    def test_assembly_time_net_rejects_the_alias(self, label):
        """Net 2: the same collision caught against the fully assembled program."""
        program = form(WHITESPACE_FORMS[label], "pub_year")
        specs = {"게재 연도": fcommon.TypedRelSpec("date", "pub_year")}
        with pytest.raises(fcommon.FactlogError, match="collides"):
            fcommon._assert_no_alias_collision(specs, program)

    def test_a_non_colliding_alias_still_loads(self):
        """Control: widening must not start rejecting KBs that were fine."""
        policy = f".decl other ({COLS})\n"
        reserved = fcommon._typed_reserved_names(
            relations=set(), predicates=fcommon.policy_predicates(policy)
        )
        specs = fcommon._parse_typed_relations(self.ALIAS_LINE, reserved)
        assert specs["게재 연도"].alias == "pub_year"
        fcommon._assert_no_alias_collision(specs, policy)  # does not raise


class TestEngineDeclPredicatesUnchanged:
    def test_the_six_engine_predicates_are_exactly_as_before(self):
        """Widening this parser is result-preserving on the real WIRELOG_PROGRAM —
        that is the point: no behaviour change today, no silent loss tomorrow."""
        assert fcommon._engine_decl_predicates() == {
            "relation",
            "canonical",
            "attr_rel",
            "edge",
            "path",
            "relation_alive",
        }


@pytest.mark.skipif(
    fcommon.EasySession is None, reason="the engine contract needs pyrewire installed"
)
class TestEngineAcceptsTheseForms:
    """The justification, re-measured. Widening our parsers is only correct while
    the ENGINE accepts these forms; if a future pyrewire rejects `p (`, this test
    fails and the reason for the widening is gone."""

    BASE = ".decl src(x: symbol)\n"
    RULE = '\np(X, "r") :- src(X).\n'

    @pytest.mark.parametrize("label", sorted(WHITESPACE_FORMS))
    def test_engine_compiles_the_form(self, label):
        decl = form(WHITESPACE_FORMS[label], cols="x: symbol, r: symbol")
        fcommon.EasySession(self.BASE + decl + self.RULE)  # no ParseError

    @pytest.mark.parametrize("name", sorted(NAME_FORMS))
    def test_engine_accepts_every_name_in_our_character_class(self, name):
        """The other side of NAME_FORMS: our grammar must not be NARROWER than the
        engine's either, or a predicate the engine derives is one we never report."""
        predicate = NAME_FORMS[name]
        fcommon.EasySession(
            self.BASE
            + f".decl {predicate} (x: symbol, r: symbol)\n"
            + f'\n{predicate}(X, "r") :- src(X).\n'
        )

    @staticmethod
    def _rows(program: str) -> list:
        session = fcommon.EasySession(program)
        session.insert("src", (session.intern("A"),))
        return [row for row in session.step() if row[0] == "p"]

    def test_a_spaced_declaration_is_taken_AS_A_DECLARATION(self):
        """What this pins is interning, not derivation — and the difference matters.

        pyrewire derives `p` rows whether or not `p` is declared, so "rows came
        back" says nothing about whether the spaced `.decl` was READ. What the
        declaration buys is the column schema: with it, the subject decodes back to
        the symbol "A"; without it, the engine has no type for that column and the
        row carries the raw id 0. So the interned value is the evidence that the
        engine accepted `.decl p (…)` AS A DECLARATION — the premise the whole fix
        rests on.

        The undeclared control is here in the body on purpose: it shows that the
        first assertion below is true either way, so nobody later mistakes it for
        the one doing the work.
        """
        declared = self._rows(self.BASE + ".decl p (x: symbol, r: symbol)\n" + self.RULE)
        undeclared = self._rows(self.BASE + self.RULE)

        assert declared and undeclared  # true with and without the .decl
        assert declared[0][1][0] == "A"  # only true when the .decl was read
        assert undeclared[0][1][0] == 0

    @pytest.mark.parametrize("ws", ["\v", "\f"])
    def test_engine_rejects_vertical_whitespace_before_a_decl(self, ws):
        """The measurement behind `[ \\t]*` rather than `\\s*` in the anchored pattern:
        these are whitespace to `\\s` and NOT whitespace to the engine."""
        with pytest.raises(Exception):
            fcommon.EasySession(
                self.BASE + f"{ws}.decl p(x: symbol, r: symbol)\n" + self.RULE
            )

    @pytest.mark.parametrize("name", ["1p", "한글술어"])
    def test_engine_rejects_names_outside_our_character_class(self, name):
        """The other half of the contract: our name grammar must not be WIDER than
        the engine's, or we would report a predicate the engine never declared."""
        with pytest.raises(Exception):
            fcommon.EasySession(self.BASE + f".decl {name}(x: symbol, r: symbol)\n")


# --- end to end ---------------------------------------------------------------

HEADER = "subject,relation,object,source,status,confidence,note"
CANDIDATES = "A,uses,B,sources/a.md,confirmed,0.90,\n"
QUERY = 'relation("A", "uses", "B")?\n'


def _env(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(REPO_ROOT), env.get("PYTHONPATH", "")]).rstrip(
        os.pathsep
    )
    env["FACTLOG_ROOT"] = str(root)
    return env


@pytest.mark.skipif(
    fcommon.EasySession is None, reason="run_logic_check needs the engine to write a report"
)
class TestReportListsASpacedPredicate:
    """The whole issue, end to end, through the real tools.

    Before the fix this report said `policy findings: 0` and
    `- no generated policy predicates` while the engine was deriving a row.
    """

    @staticmethod
    def _report(tmp_path: Path, slug: str, policy: str) -> str:
        kb = tmp_path / f"kb_{slug}"
        subprocess.run(
            [sys.executable, "-m", "factlog", "init", "--target", str(kb)],
            check=True,
            capture_output=True,
            env=_env(tmp_path),
        )
        (kb / "sources" / "a.md").write_text("a\n", encoding="utf-8")
        (kb / "facts" / "candidates.csv").write_text(f"{HEADER}\n{CANDIDATES}", encoding="utf-8")
        (kb / "facts" / "query.dl").write_text(QUERY, encoding="utf-8")
        (kb / "policy" / "logic-policy.dl").write_text(policy, encoding="utf-8")
        subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "compile_facts.py")],
            cwd=kb,
            check=True,
            capture_output=True,
            env=_env(kb),
        )
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "run_logic_check.py")],
            cwd=kb,
            capture_output=True,
            text=True,
            env=_env(kb),
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return (kb / "facts" / "logic_report.txt").read_text(encoding="utf-8")

    @pytest.mark.parametrize("name", sorted(NAME_FORMS))
    def test_every_accepted_name_reaches_the_report(self, tmp_path, name):
        """policy_predicates returning a MixedCase name is not the same claim as the
        report RENDERING it — the value travels through run_logic_check's query and
        row rendering before a human sees it. Pinned end to end so the name grammar
        is not correct only up to the point where it stops being tested."""
        predicate = NAME_FORMS[name]
        report = self._report(
            tmp_path,
            f"name_{name.replace(' ', '_')}",
            f".decl {predicate} ({COLS})\n"
            + f'{predicate}(X, "probe") :- relation(X, "uses", _).\n',
        )
        assert "policy findings: 1" in report.splitlines(), report
        assert f"- {predicate}: 1 rows" in report.splitlines(), report

    @pytest.mark.parametrize(
        "label", ["tight", "one space", "tab", "newline", "indented and spaced"]
    )
    def test_report_counts_the_finding(self, tmp_path, label):
        kb = tmp_path / f"kb_{label.replace(' ', '_')}"
        subprocess.run(
            [sys.executable, "-m", "factlog", "init", "--target", str(kb)],
            check=True,
            capture_output=True,
            env=_env(tmp_path),
        )
        (kb / "sources" / "a.md").write_text("a\n", encoding="utf-8")
        (kb / "facts" / "candidates.csv").write_text(f"{HEADER}\n{CANDIDATES}", encoding="utf-8")
        (kb / "facts" / "query.dl").write_text(QUERY, encoding="utf-8")
        decl = form(WHITESPACE_FORMS[label], "probe_pred")
        (kb / "policy" / "logic-policy.dl").write_text(
            decl + 'probe_pred(X, "probe") :- relation(X, "uses", _).\n',
            encoding="utf-8",
        )
        subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "compile_facts.py")],
            cwd=kb,
            check=True,
            capture_output=True,
            env=_env(kb),
        )
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "run_logic_check.py")],
            cwd=kb,
            capture_output=True,
            text=True,
            env=_env(kb),
        )
        assert result.returncode == 0, result.stdout + result.stderr
        report = (kb / "facts" / "logic_report.txt").read_text(encoding="utf-8")
        assert "policy findings: 1" in report.splitlines(), report
        assert "- probe_pred: 1 rows" in report.splitlines(), report
