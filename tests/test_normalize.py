"""Unit tests for the normalization ladder (design 2.3, 2.6)."""

import pytest

from ttbverify.models import Outcome
from ttbverify.normalize import (
    FUZZY_REVIEW_THRESHOLD,
    compare,
    levenshtein,
    punct_norm,
    similarity,
)


class TestLadderTiers:
    def test_exact_match(self):
        r = compare("OLD TOM DISTILLERY", "OLD TOM DISTILLERY")
        assert r.outcome is Outcome.PASS
        assert r.tier == "exact"

    def test_whitespace_only_difference_is_still_exact(self):
        r = compare("OLD  TOM   DISTILLERY", "OLD TOM DISTILLERY")
        assert r.outcome is Outcome.PASS
        assert r.tier == "exact"

    def test_stones_throw_case_only(self):
        # The canonical case from the brief: label all-caps, application title-case.
        r = compare("Stone's Throw", "STONE'S THROW")
        assert r.outcome is Outcome.PASS
        assert r.tier == "case"

    def test_curly_vs_straight_apostrophe(self):
        r = compare("Stone’s Throw", "Stone's Throw")
        assert r.outcome is Outcome.PASS
        assert r.tier in ("case", "punctuation")

    def test_ampersand_vs_and(self):
        r = compare("Smith & Sons", "Smith and Sons")
        assert r.outcome is Outcome.PASS
        assert r.tier == "punctuation"

    def test_trailing_company_suffix_ignored(self):
        r = compare("Old Tom Distillery, LLC", "Old Tom Distillery")
        assert r.outcome is Outcome.PASS
        assert r.tier == "punctuation"

    def test_close_miss_goes_to_review_not_fail(self):
        r = compare("Old Tom Distillery", "Old Tom Distellery")  # one transposed-ish char
        assert r.outcome is Outcome.REVIEW
        assert r.tier == "fuzzy"
        assert r.similarity >= FUZZY_REVIEW_THRESHOLD

    def test_genuinely_different_brand_fails(self):
        r = compare("Old Tom Distillery", "Rusty Anchor Rum Co.")
        assert r.outcome is Outcome.FAIL
        assert r.tier == "mismatch"

    def test_empty_observation_is_not_a_pass(self):
        r = compare("Old Tom Distillery", "")
        assert r.outcome is Outcome.FAIL


class TestPunctNormProperties:
    @pytest.mark.parametrize(
        "text",
        [
            "Stone's Throw, LLC",
            "SMITH & SONS  Inc.",
            "Château Margaux",
            "A.B.C. Distillers Co.",
            "  weird   spacing  ",
        ],
    )
    def test_idempotent(self, text):
        once = punct_norm(text)
        assert punct_norm(once) == once

    def test_drops_only_trailing_suffixes(self):
        # "Co" in the middle of a name is not a suffix and must survive.
        assert "coconut" in punct_norm("Coconut Bay Rum")


class TestSimilarity:
    def test_identical(self):
        assert similarity("abc", "abc") == 1.0

    def test_both_empty(self):
        assert similarity("", "") == 1.0

    def test_levenshtein_basic(self):
        assert levenshtein("kitten", "sitting") == 3

    def test_symmetry(self):
        assert levenshtein("abcdef", "abcxef") == levenshtein("abcxef", "abcdef")
