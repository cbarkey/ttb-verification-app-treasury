"""Accuracy layer for the *realistic* corpus (fixtures/realistic.py).

The clean corpus (test_corpus.py) proves the rules on ideal input. This layer
proves the pipeline survives real-label styling — colour grounds, serif display
faces, framed borders, wrapped brand names, boxed and rotated warnings, and a
"photo of the bottle" degradation pass.

Cases are graded:

  * ``exact`` — realistic styling, no geometric degradation; every listed check
    must match ground truth, exactly like the clean corpus.
  * ``loose`` — degraded (rotation / perspective / low light). A clean field may
    soften to REVIEW/UNREADABLE; a genuine defect must still never read PASS.

The gate that holds for the whole set, regardless of grade: **no false
approvals** — a FAIL/REVIEW ground-truth cell must never come back PASS.

Needs the tesseract binary; skipped without it.
"""

from __future__ import annotations

import pytest

from fixtures import load_realistic_cases
from ttbverify.models import LabelApplication
from ttbverify.pipeline import verify

pytestmark = [pytest.mark.corpus, pytest.mark.realistic]

_HARD = {"FAIL", "REVIEW"}


@pytest.fixture(scope="module")
def results(tesseract_or_skip):
    engine = tesseract_or_skip
    out = {}
    for case in load_realistic_cases():
        app = LabelApplication(**case["application"])
        out[case["case_id"]] = (case, verify(app, engine))
    return out


def _ids(grade: str | None = None) -> list[str]:
    try:
        cases = load_realistic_cases()
    except FileNotFoundError:
        return []
    return [c["case_id"] for c in cases if grade is None or c["grade"] == grade]


def test_no_false_approvals_on_realistic_corpus(results):
    """The one gate that never relaxes."""
    offenders = []
    for case_id, (case, result) in results.items():
        by_id = {c.check_id: c.outcome.value for c in result.checks}
        for check_id, expected in case["expect"].items():
            if expected in _HARD and by_id.get(check_id) == "PASS":
                offenders.append(f"{case_id}/{check_id} expected {expected}, got PASS")
    assert not offenders, "\n".join(offenders)


@pytest.mark.parametrize("case_id", _ids("exact"))
def test_exact_case_matches_ground_truth(results, case_id):
    case, result = results[case_id]
    by_id = {c.check_id: c.outcome.value for c in result.checks}
    mismatches = [
        f"{cid}: expected {exp}, got {by_id.get(cid, 'MISSING')}"
        for cid, exp in case["expect"].items()
        if exp != "MISSING" and by_id.get(cid, "MISSING") != exp
    ]
    assert not mismatches, f"{case_id}: " + "; ".join(mismatches)


@pytest.mark.parametrize("case_id", _ids("loose"))
def test_loose_case_defects_survive_degradation(results, case_id):
    """On a degraded image, a real defect must not be washed out to PASS."""
    case, result = results[case_id]
    by_id = {c.check_id: c.outcome.value for c in result.checks}
    leaked = [
        f"{cid}: {exp} degraded to PASS"
        for cid, exp in case["expect"].items()
        if exp in _HARD and by_id.get(cid) == "PASS"
    ]
    assert not leaked, f"{case_id}: " + "; ".join(leaked)


@pytest.mark.parametrize("case_id", _ids("exact"))
def test_realistic_styling_does_not_blind_the_pipeline(results, case_id):
    """Undegraded realistic labels: the brand and the warning must be located."""
    _, result = results[case_id]
    by_id = {c.check_id: c for c in result.checks}
    assert by_id["brand"].outcome.value != "UNREADABLE", "brand not located"
    assert by_id["warn_present"].outcome.value == "PASS", "warning not located"


def test_realistic_single_label_p95_under_budget(results):
    timings = sorted(r.elapsed_ms for _, r in results.values())
    p95 = timings[min(len(timings) - 1, max(0, round(0.95 * len(timings)) - 1))]
    assert p95 < 5000, f"p95 {p95} ms exceeds the 5000 ms budget (N-01)"
