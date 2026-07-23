# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the shared PMID fold (#428).

The fold and its give-up condition used to live privately in ``source_writer``;
#428 needed the same rule at the export boundary and moved it here rather than
copying it, exactly as #420 did for the DOI prefix. These tests pin the shared
contract, and the last class pins that the join key really does delegate — a
second copy would pass every other test in this file while drifting.
"""
from __future__ import annotations

from factlog.integrations.common.pmid import fold_pmid
from factlog.integrations.common.source_writer import normalize_cross_id


class TestTheWholeValueFolds:
    def test_full_width_digits_become_ascii(self):
        assert fold_pmid("１２３４５６７８") == "12345678"

    def test_ascii_value_is_unchanged(self):
        assert fold_pmid("16354850") == "16354850"

    def test_other_decimal_scripts_fold_too(self):
        # `Nd` is wider than the full-width forms, and NFKC would leave these be.
        assert fold_pmid("٢٣٤") == "234"  # Arabic-Indic
        assert fold_pmid("२३४") == "234"  # Devanagari

    def test_mixed_scripts_fold_to_one_number(self):
        assert fold_pmid("１2٣") == "123"

    def test_no_part_is_held_back(self):
        # The whole-value fold is the difference from the DOI rule, which keeps an
        # opaque suffix. A PMID has no opaque half, so nothing is preserved: this
        # is the test that fails if someone reuses the DOI's prefix-only shape.
        assert fold_pmid("１２３４５６７８") == "12345678"
        assert not any(ch.isdecimal() and not ch.isascii() for ch in fold_pmid("１２３"))


class TestItRefusesWhatItCannotParse:
    def test_a_label_is_returned_unchanged(self):
        assert fold_pmid("pmid:１２３") == "pmid:１２３"

    def test_a_url_is_returned_unchanged(self):
        assert fold_pmid("https://pubmed.ncbi.nlm.nih.gov/１２３") == \
            "https://pubmed.ncbi.nlm.nih.gov/１２３"

    def test_a_partial_match_returns_the_original_not_the_fold(self):
        # The subtle one: `fold_decimal_digits` runs over the WHOLE string before
        # the check, so the folded candidate here is `123abc`. Returning that
        # would hand the caller a half-normalized value it never asked for. The
        # original comes back instead.
        assert fold_pmid("１２３abc") == "１２３abc"

    def test_whitespace_is_not_stripped(self):
        # This function folds; it does not trim. `normalize_cross_id` strips
        # before calling, and that split of duties is what keeps this one able to
        # say "unchanged" and mean it.
        assert fold_pmid(" １２３ ") == " １２３ "

    def test_empty_stays_empty(self):
        # `[0-9]+` needs at least one digit, so "" takes the refuse branch and is
        # returned as-is. Named because the answer is the same either way and a
        # reader should not have to work out that it is not an accident.
        assert fold_pmid("") == ""

    def test_superscript_and_circled_digits_are_not_pmid_digits(self):
        # Category `No`, not `Nd`. `\d` never matched them and NFKC would have,
        # which is why the fold underneath is not NFKC.
        assert fold_pmid("1²3") == "1²3"
        assert fold_pmid("①②③") == "①②③"


class TestTheJoinKeyDelegatesHere:
    """The single-source claim: ``normalize_cross_id("pmid", …)`` is this fold."""

    def test_join_key_matches_the_fold_on_every_shape(self):
        for value in ("１２３４５６７８", "16354850", "pmid:１２３", "１２３abc", "٢٣٤", ""):
            assert normalize_cross_id("pmid", value) == fold_pmid(value)

    def test_the_join_key_adds_only_the_strip(self):
        # What `normalize_cross_id` does that this function deliberately does not.
        # Written as an inequality as well as an equality: an assertion that only
        # said "they agree" would also pass if this module started stripping.
        assert normalize_cross_id("pmid", " １２３ ") == "123"
        assert fold_pmid(" １２３ ") != "123"
