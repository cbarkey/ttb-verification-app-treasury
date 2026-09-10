"""Golden / accuracy layer (design 2.6, 7.4).

Runs every generated fixture through the real pipeline (Tesseract + NullVlm) and
asserts the per-check outcome matches the checked-in ground truth. Also asserts
the two hard gates as tests, not prose:

  * zero false approvals  (a FAIL/REVIEW ground-truth cell landing on PASS)
  * single-label p95 < 5 s (N-01)

Skipped entirely when the `tesseract` binary is not installed — this layer needs
it; the pure-function layers (test_normalize/test_parsers/test_warning/test_rules)
do not.
"""

from __future__ import annotations

import pytest

from fixtures import load_cases
from ttbverify.models import LabelApplication
from ttbverify.pipeline import verify

pytestmark = pytest.mark.corpus


@pytest.fixture(scope="module")
def results(tesseract_or_skip):
    engine = tesseract_or_skip
    out = {}
    for case in load_cases():
        app = LabelApplication(**case["application"])
        out[case["case_id"]] = (case, verify(app, engine))
    return out


def _cases_and_ids():
    try:
        cases = load_cases()
    except FileNotFoundError:  # fixtures not generated yet
        return []
    return [(c["case_id"],) for c in cases]


@pytest.mark.parametrize("case_id", [c[0] for c in _cases_and_ids()])
def test_case_matches_ground_truth(results, case_id):
    case, result = results[case_id]
    by_id = {c.check_id: c.outcome.value for c in result.checks}
    mismatches = []
    for check_id, expected in case["expect"].items():
        got = by_id.get(check_id, "MISSING")
        if got != expected:
            mismatches.append(f"{check_id}: expected {expected}, got {got}")
    assert not mismatches, f"{case_id}: " + "; ".join(mismatches)


def test_zero_false_approvals(results):
    """The single most important number in the project (design 7.4)."""
    offenders = []
    for case_id, (case, result) in results.items():
        by_id = {c.check_id: c.outcome.value for c in result.checks}
        for check_id, expected in case["expect"].items():
            if expected in ("FAIL", "REVIEW") and by_id.get(check_id) == "PASS":
                offenders.append(f"{case_id}/{check_id}")
    assert not offenders, f"false approvals: {offenders}"


def test_brand_and_class_do_not_cross_contaminate(results):
    """Every check must point at its *own* text — the brand box must not be the
    class/type line and vice versa. Outcome gates alone don't catch this."""
    bad = []
    for case_id, (_case, result) in results.items():
        by_id = {c.check_id: c for c in result.checks}
        brand, cls = by_id.get("brand"), by_id.get("class_type")
        if not (brand and cls and brand.box and cls.box):
            continue
        bo, co = (brand.observed or "").strip(), (cls.observed or "").strip()
        if bo and co and bo == co:
            bad.append(f"{case_id}: brand and class both read {bo!r}")
        elif (abs(brand.box.top - cls.box.top) < 6
              and abs(brand.box.height - cls.box.height) < 6):
            bad.append(f"{case_id}: brand box coincides with the class box")
    assert not bad, "\n".join(bad)


def test_warning_recall_on_mutation_set(results):
    """Every warning-statement defect fixture must be caught (recall 1.0)."""
    defects = {
        "warning_missing": "warn_present",
        "warning_reworded": "warn_text",
        "warning_titlecase": "warn_case",
    }
    for case_id, check_id in defects.items():
        _, result = results[case_id]
        outcome = next(c.outcome.value for c in result.checks if c.check_id == check_id)
        assert outcome in ("FAIL", "REVIEW"), f"{case_id}/{check_id} was {outcome}"


def test_single_label_p95_under_budget(results):
    timings = sorted(r.elapsed_ms for _, r in results.values())
    p95 = timings[min(len(timings) - 1, max(0, round(0.95 * len(timings)) - 1))]
    assert p95 < 5000, f"p95 {p95} ms exceeds the 5000 ms budget (N-01)"
