"""Unit tests for the health warning checks (design 2.3, 3.3, 3.4).

These feed synthetic OCR pages directly so the two-band W-2 logic and the W-3
casing rule can be exercised with controlled, OCR-like input.
"""


from tests.conftest import make_page
from ttbverify.models import Outcome
from ttbverify.warning import (
    REFERENCE_WARNING,
    compare_wording,
    evaluate,
    locate,
)

BODY = REFERENCE_WARNING


def _tokens(s: str) -> list[str]:
    return s.split()


class TestWording:
    def test_exact_reference_passes(self):
        assert compare_wording(_tokens(REFERENCE_WARNING)).outcome is Outcome.PASS

    def test_single_character_misread_is_review_not_fail(self):
        noisy = REFERENCE_WARNING.replace("machinery", "machinory")
        report = compare_wording(_tokens(noisy))
        assert report.outcome is Outcome.REVIEW
        assert report.noise_positions

    def test_two_char_misread_still_review(self):
        noisy = REFERENCE_WARNING.replace("Consumption", "Consurnption")
        assert compare_wording(_tokens(noisy)).outcome is Outcome.REVIEW

    def test_genuine_rewording_fails_with_diff(self):
        reworded = REFERENCE_WARNING.replace("operate machinery", "use heavy equipment")
        report = compare_wording(_tokens(reworded))
        assert report.outcome is Outcome.FAIL
        assert any(d["kind"] == "substituted" for d in report.hard_mismatches)

    def test_omitted_word_fails(self):
        dropped = REFERENCE_WARNING.replace("birth defects", "defects")
        report = compare_wording(_tokens(dropped))
        assert report.outcome is Outcome.FAIL
        assert any(d["kind"] == "missing" for d in report.diff)

    def test_case_difference_alone_is_not_a_wording_failure(self):
        # W-2 casefolds; casing is W-3's job.
        shouted = REFERENCE_WARNING.upper()
        assert compare_wording(_tokens(shouted)).outcome is Outcome.PASS


class TestLocateAndEvaluate:
    def test_locates_on_back_page(self):
        pages = [
            make_page("FRONT LABEL BRAND\nSome Class Type", index=0, role="front"),
            make_page(REFERENCE_WARNING, index=1, role="back"),
        ]
        loc = locate(pages)
        assert loc is not None and loc.page_index == 1

    def test_absent_warning_yields_four_non_pass_checks(self):
        pages = [make_page("BRAND\n40% Alc./Vol.\n750 mL", index=0, role="front")]
        checks = evaluate(pages)
        assert {c.check_id for c in checks} == {
            "warn_present", "warn_text", "warn_case", "warn_bold"}
        assert all(c.outcome is Outcome.FAIL for c in checks)

    def test_clean_warning_full_evaluate(self):
        pages = [make_page(REFERENCE_WARNING, index=0, role="back")]
        by_id = {c.check_id: c for c in evaluate(pages)}
        assert by_id["warn_present"].outcome is Outcome.PASS
        assert by_id["warn_text"].outcome is Outcome.PASS
        assert by_id["warn_case"].outcome is Outcome.PASS
        # W-4 is never auto-decided (design 3.4).
        assert by_id["warn_bold"].outcome is Outcome.REVIEW

    def test_titlecase_header_fails_w3_only(self):
        tc = REFERENCE_WARNING.replace("GOVERNMENT WARNING", "Government Warning")
        by_id = {c.check_id: c for c in evaluate([make_page(tc, role="back")])}
        assert by_id["warn_case"].outcome is Outcome.FAIL
        assert by_id["warn_text"].outcome is Outcome.PASS

    def test_ocr_unavailable_is_unreadable_never_pass(self):
        checks = evaluate([], ocr_available=False)
        assert all(c.outcome is Outcome.UNREADABLE for c in checks)

    def test_w4_always_review_even_when_present_and_bold(self):
        by_id = {c.check_id: c for c in evaluate([make_page(REFERENCE_WARNING, role="back")])}
        assert by_id["warn_bold"].outcome is Outcome.REVIEW
        assert "header_dark_ratio" in by_id["warn_bold"].evidence
