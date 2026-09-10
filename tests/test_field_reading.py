"""Per-field reading: does each check read the *right text*, from the *right image*?

The outcome gates (test_corpus / test_realistic) assert verdicts. A verdict can
be right for the wrong reason — a check pointing at another check's line, or a
fixture whose brand ran off the edge of the label and was never OCR'd at all,
both still produce the expected FAIL. Both of those actually happened.

So every generated case also records, per check, what the label says and which
image it says it on (`expect_observed`, emitted by the fixture generators), and
this module asserts the pipeline against it:

  matched             observed text matches the label's own text (via the
                      normalization ladder, so OCR noise is tolerated) and comes
                      from the expected image
  only_in_fine_print  the declared value IS on the label but buried in a longer
                      statement — must FAIL, and must say so (design 3.2)
  not_found           the declared value isn't on the label — must FAIL with
                      observed = None. No guessing what the label "probably" says.

Degraded fixtures (rotation / keystone / low light) are exempt: some fields
genuinely can't be read there, and pinning current behaviour would just bake in
the limitation. They're still covered by the no-false-approval gates.

Needs the tesseract binary; skipped without it.
"""

from __future__ import annotations

import contextlib

import pytest

from fixtures import load_cases, load_realistic_cases
from ttbverify.models import LabelApplication, Outcome
from ttbverify.normalize import compare
from ttbverify.pipeline import verify

pytestmark = pytest.mark.corpus

TEXT_FIELDS = ("brand", "class_type", "producer", "address", "origin")


def _all_cases() -> list[dict]:
    out: list[dict] = []
    for loader in (load_cases, load_realistic_cases):
        with contextlib.suppress(FileNotFoundError):  # corpus not generated yet
            out.extend(loader())
    return [c for c in out if not c.get("degraded")]


def _ids() -> list[str]:
    return [c["case_id"] for c in _all_cases()]


@pytest.fixture(scope="module")
def results(tesseract_or_skip):
    engine = tesseract_or_skip
    out = {}
    for case in _all_cases():
        app = LabelApplication(**case["application"])
        out[case["case_id"]] = (case, verify(app, engine))
    return out


def _check_fact(check, fact) -> list[str]:
    """Return a list of problems (empty if the reading is correct)."""
    status = fact["status"]
    problems: list[str] = []

    if status == "not_found":
        if check.outcome is not Outcome.FAIL:
            problems.append(f"expected FAIL, got {check.outcome.value}")
        if check.observed is not None:
            problems.append(f"should report nothing, but claims {check.observed!r}")
        return problems

    if status == "only_in_fine_print":
        if check.outcome is not Outcome.FAIL:
            problems.append(f"expected FAIL, got {check.outcome.value}")
        if check.evidence.get("match") != "only_in_fine_print":
            problems.append("should be flagged as found only in fine print, "
                            f"got match={check.evidence.get('match')!r}")
        return problems

    # matched
    if check.observed is None:
        problems.append(f"read nothing; the label says {fact['text']!r} "
                        f"({check.outcome.value})")
        return problems
    if compare(fact["text"], check.observed).outcome is not Outcome.PASS:
        problems.append(f"read {check.observed!r}, but the label says {fact['text']!r}")
    # The image is asserted against every image the label prints this value on,
    # not just the first — a brand repeated as a heading on the back label is
    # genuinely readable from either (see `fixtures.text_fact`).
    where = fact.get("images")
    if where and check.image_index not in where:
        problems.append(f"read from image {check.image_index}, "
                        f"expected one of {where}")
    return problems


@pytest.mark.parametrize("case_id", _ids())
def test_every_field_reads_its_own_text(results, case_id):
    case, result = results[case_id]
    by_id = {c.check_id: c for c in result.checks}
    failures: list[str] = []
    for check_id, fact in case["expect_observed"].items():
        if fact is None:                      # nothing declared -> NOT_DECLARED
            check = by_id.get(check_id)
            if check and check.outcome not in (Outcome.NOT_DECLARED, Outcome.PASS):
                failures.append(f"{check_id}: nothing declared but got "
                                f"{check.outcome.value}")
            continue
        check = by_id.get(check_id)
        if check is None:
            failures.append(f"{check_id}: check missing from the result")
            continue
        for problem in _check_fact(check, fact):
            failures.append(f"{check_id}: {problem}")
    assert not failures, f"{case_id}\n  " + "\n  ".join(failures)


@pytest.mark.parametrize("case_id", _ids())
def test_checks_for_different_values_read_different_text(results, case_id):
    """Two checks looking for *different* declared values must not come back
    with the same text — that's a check borrowing another one's line.

    Checks looking for the *same* value legitimately coincide: on most of these
    labels the distillery is also the brand, so `producer` and `brand` reading
    "OLD TOM DISTILLERY" is correct, not a collision.
    """
    from ttbverify.normalize import punct_norm

    _case, result = results[case_id]
    seen: dict[str, tuple[str, str]] = {}      # observed -> (check_id, declared)
    clashes = []
    for c in result.checks:
        if c.check_id.startswith("warn") or not c.observed or not c.box:
            continue
        if c.check_id in ("abv", "proof"):     # legitimately share the ABV line
            continue
        key = punct_norm(c.observed)
        prev = seen.get(key)
        if prev and punct_norm(prev[1] or "") != punct_norm(c.declared or ""):
            clashes.append(
                f"{c.check_id} (looking for {c.declared!r}) and {prev[0]} "
                f"(looking for {prev[1]!r}) both read {c.observed!r}")
        seen.setdefault(key, (c.check_id, c.declared))
    assert not clashes, f"{case_id}: " + "; ".join(clashes)


def test_the_corpus_audit_catches_an_illegible_field(tesseract_or_skip):
    """The guard that would have caught the overflowing brand. Prove it fires:
    claim a label prints something it doesn't, and the audit must object."""
    from fixtures import audit_corpus

    real = load_cases()[0]
    bogus = {
        "case_id": "synthetic_broken",
        "degraded": False,
        "application": real["application"],
        "expect_observed": {
            "brand": {"status": "matched", "text": "TEXT THAT IS NOT ON THIS LABEL",
                      "printed": "TEXT THAT IS NOT ON THIS LABEL", "images": [0]},
        },
    }
    problems = audit_corpus([bogus])
    assert problems and "synthetic_broken" in problems[0]

    # ...and stays quiet on a label that really does print what it claims
    assert audit_corpus([real]) == []


def test_the_corpus_audit_is_not_satisfied_by_fine_print(tesseract_or_skip):
    """The hole the first version of this audit had, and the reason it exists.

    `brand_mismatch` plants the declared brand inside the bottler statement while
    the label's actual display brand is something else. An audit that asks "is
    this string anywhere in the image's text" is happy with that — which is
    exactly the state a brand clipped off the edge of the label leaves behind, so
    the audit would have gone on passing the very defect it was written for. A
    display field has to be legible as a *line*.
    """
    from fixtures import audit_corpus

    decoy = next(c for c in load_cases() if c["case_id"] == "brand_mismatch")
    declared = decoy["application"]["brand_name"]
    bogus = {
        "case_id": "synthetic_fineprint_only",
        "degraded": False,
        "application": decoy["application"],
        # Claim the declared brand is the display brand. It is not — it appears
        # only inside the bottler statement.
        "expect_observed": {
            "brand": {"status": "matched", "text": declared, "printed": declared,
                      "images": [0]},
        },
    }
    problems = audit_corpus([bogus])
    assert problems and "brand" in problems[0]


def test_a_declared_brand_hidden_in_fine_print_is_never_approved(results):
    """Design 3.2, stated as a gate over the whole corpus."""
    offenders = []
    for case_id, (case, result) in results.items():
        fact = case["expect_observed"].get("brand")
        if not fact or fact["status"] != "only_in_fine_print":
            continue
        brand = next(c for c in result.checks if c.check_id == "brand")
        if brand.outcome is not Outcome.FAIL:
            offenders.append(f"{case_id}: brand {brand.outcome.value}")
    assert not offenders, f"false approvals from a fine-print brand: {offenders}"
