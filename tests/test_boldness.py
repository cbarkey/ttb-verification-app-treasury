"""W-4 boldness auto-confirm — calibration + gates (fixtures/boldness.py).

W-4 auto-PASSes only when "GOVERNMENT WARNING" is confidently heavier than the
regular-weight remainder of the same statement; otherwise REVIEW. It never
auto-FAILs. These tests hold that line against a matched corpus (6 families,
regular vs bold, two sizes, clean and mildly degraded, plus adversarial cases).

  grade "decidable" — clean, ≥15 px, same family: the metric should get it right
  grade "review_ok" — small / degraded / adversarial: REVIEW is a fine answer

The gate that never relaxes across the whole set: a regular-weight header must
never auto-PASS. Coverage on the decidable set is reported, not gated — it's the
"is this worth doing" number.

Needs the tesseract binary; skipped without it.
"""

from __future__ import annotations

import pytest

from fixtures import load_boldness_cases
from ttbverify import warning
from ttbverify.ocr import TesseractOcr
from ttbverify.warning import assess_boldness

pytestmark = [pytest.mark.corpus, pytest.mark.boldness]


@pytest.fixture(scope="module")
def results(tesseract_or_skip):
    from PIL import Image

    engine: TesseractOcr = tesseract_or_skip
    out = {}
    for case in load_boldness_cases():
        page = engine.read(case["image"]["path"], 0, "back")
        loc = warning.locate([page])
        img = Image.open(case["image"]["path"])
        outcome, ev = assess_boldness(loc, img) if loc else (None, {})
        out[case["case_id"]] = (case, outcome, ev)
    return out


def _ids(grade: str | None = None) -> list[str]:
    try:
        cases = load_boldness_cases()
    except FileNotFoundError:
        return []
    return [c["case_id"] for c in cases if grade is None or c["grade"] == grade]


def test_regular_header_never_auto_passes(results):
    """The gate. A regular-weight header must never be auto-confirmed as bold."""
    leaked = [
        cid for cid, (case, outcome, _ev) in results.items()
        if case["expect_bold"] is False and outcome is not None
        and outcome.value == "PASS"
    ]
    assert not leaked, f"regular headers auto-PASSed: {leaked}"


def test_w4_never_auto_fails(results):
    """Design 3.4 / §2.3: W-4 routes uncertainty to a human, it does not reject."""
    fails = [cid for cid, (_c, outcome, _e) in results.items()
             if outcome is not None and outcome.value == "FAIL"]
    assert not fails, f"W-4 auto-FAILed: {fails}"


@pytest.mark.parametrize("case_id", _ids("decidable"))
def test_decidable_case_is_correct(results, case_id):
    case, outcome, _ev = results[case_id]
    assert outcome is not None, "warning not located"
    if case["expect_bold"] is True:
        assert outcome.value == "PASS", "clear bold header should auto-confirm"
    else:
        assert outcome.value == "REVIEW", "regular header should go to review, not pass"


def test_decidable_coverage_is_reported(results):
    dec = [(c, o) for _cid, (c, o, _e) in results.items() if c["grade"] == "decidable"]
    decided = sum(1 for _c, o in dec if o is not None and o.value in ("PASS", "FAIL"))
    coverage = decided / len(dec)
    # Not a hard gate — but if the metric can't confidently decide *any* clean
    # same-family case, review-by-default was the right call after all.
    assert coverage > 0.3, f"only {coverage:.0%} of decidable cases auto-decided"
    print(f"\nW-4 auto-decide coverage on decidable cases: {coverage:.0%} "
          f"({decided}/{len(dec)})")


def test_adversarial_thin_header_not_passed(results):
    """The sharpest case: a header set *lighter* than the body it sits in.

    Skipped where the corpus couldn't be built as described — the generator
    drops cases whose fonts would have silently substituted, because a "thin
    light header" that resolved to a plain sans face is a different picture
    making a different claim, and this assertion would then be testing the
    opposite of what the image shows (`fixtures/boldness.py::_usable`).
    """
    if "b_adv_thin_light" not in results:
        pytest.skip("no genuinely light face on this machine — case not generated")
    _case, outcome, ev = results["b_adv_thin_light"]
    assert outcome.value != "PASS", f"thin header auto-PASSed (ratio {ev.get('weight_ratio')})"
