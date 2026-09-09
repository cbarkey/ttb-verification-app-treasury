"""Unit tests for ABV/proof and net-contents parsing (design 2.3, 3.5)."""

import pytest

from ttbverify.parsers import (
    parse_abv,
    parse_net_contents,
    to_milliliters,
)


class TestAbvParsing:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("45% Alc./Vol. (90 Proof)", 45.0),
            ("ALC 45% BY VOL", 45.0),
            ("45% ABV", 45.0),
            ("Alc. 45% by Vol.", 45.0),
            ("40.5% Alc/Vol", 40.5),
            ("13.5% alcohol by volume", 13.5),
        ],
    )
    def test_abv_phrasings(self, text, expected):
        assert parse_abv(text).abv == expected

    def test_proof_extracted(self):
        r = parse_abv("45% Alc./Vol. (90 Proof)")
        assert r.proof == 90.0
        assert r.proof_consistent is True

    def test_proof_inconsistent_flagged(self):
        r = parse_abv("45% Alc./Vol. (100 Proof)")
        assert r.proof_consistent is False

    def test_proof_consistency_none_without_both(self):
        assert parse_abv("45% ABV").proof_consistent is None
        assert parse_abv("no numbers here").proof_consistent is None

    def test_rounding_slack_allowed(self):
        # 40.3% -> 80.6 proof, label rounds to 81. Should still read as consistent.
        assert parse_abv("40.3% Alc/Vol (81 Proof)").proof_consistent is True

    def test_picks_alcohol_percentage_among_several(self):
        # "70% of the grapes ... 14% Alc./Vol." -> the alcohol one wins.
        r = parse_abv("Made with 70% Merlot grapes. 14% Alc./Vol.")
        assert r.abv == 14.0

    def test_nothing_parseable(self):
        assert parse_abv("").abv is None
        assert parse_abv("bottled by hand").abv is None


class TestNetContents:
    @pytest.mark.parametrize(
        "text,expected_ml",
        [
            ("750 mL", 750.0),
            ("750ML", 750.0),
            ("0.75 L", 750.0),
            ("75 cL", 750.0),
            ("1 L", 1000.0),
            ("1.5L", 1500.0),
            ("12 fl oz", pytest.approx(354.882, rel=1e-3)),
            ("12 FL. OZ.", pytest.approx(354.882, rel=1e-3)),
        ],
    )
    def test_unit_normalization(self, text, expected_ml):
        assert parse_net_contents(text).milliliters == expected_ml

    def test_equivalent_values_compare_equal(self):
        a = parse_net_contents("750 mL").milliliters
        b = parse_net_contents("0.75 L").milliliters
        assert a == b

    def test_unparseable(self):
        assert parse_net_contents("family size").milliliters is None
        assert parse_net_contents("").milliliters is None

    def test_to_milliliters_unknown_unit(self):
        assert to_milliliters(1.0, "furlongs") is None
