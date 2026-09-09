"""Accuracy + latency report over the fixture corpus (design 2.6).

Runs every generated case through the real pipeline (Tesseract OCR, NullVlm),
compares outcomes against the checked-in ground truth, and gates on the two
numbers that matter:

  * false approval rate   -> must be 0   (a FAIL/REVIEW case landing on PASS)
  * expectation mismatches -> must be 0  (any outcome != ground truth)

Also prints p50/p95 latency vs the 5 s budget (N-01) and the (reported, not
gated) review rate, and burns the review-overlay boxes into PNGs under out/ so
the coordinates the review screen will need can be eyeballed without a frontend.

Run:  python report.py
"""

from __future__ import annotations

import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows console is cp1252 by default
except Exception:
    pass

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from fixtures import (  # noqa: E402
    REPO_ROOT, load_boldness_cases, load_cases, load_realistic_cases,
)
from ttbverify import warning  # noqa: E402
from ttbverify.models import LabelApplication, Outcome  # noqa: E402
from ttbverify.ocr import NullOcr, TesseractOcr  # noqa: E402
from ttbverify.pipeline import verify  # noqa: E402

OUT = os.path.join(REPO_ROOT, "out")

_COLOR = {
    Outcome.PASS: (34, 139, 34),
    Outcome.REVIEW: (218, 145, 0),
    Outcome.FAIL: (200, 30, 30),
    Outcome.UNREADABLE: (110, 110, 110),
    Outcome.NOT_DECLARED: (150, 150, 150),
}


def _overlay(app: LabelApplication, result, path: str) -> None:
    base = Image.open(app.images[0].path).convert("RGB")
    draw = ImageDraw.Draw(base, "RGBA")
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except OSError:
        font = ImageFont.load_default(16)
    for check in result.checks:
        if not check.box or (check.image_index or 0) != 0:
            continue
        b = check.box
        color = _COLOR[check.outcome]
        draw.rectangle([b.left - 4, b.top - 4, b.right + 4, b.bottom + 4],
                       outline=color, width=3)
        tag = f"{check.check_id}:{check.outcome.value}"
        tw = draw.textlength(tag, font=font)
        draw.rectangle([b.left - 4, b.top - 24, b.left + tw + 6, b.top - 4], fill=color)
        draw.text((b.left, b.top - 22), tag, font=font, fill="white")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    base.save(path)


def main() -> int:
    cases = load_cases()
    engine = TesseractOcr() if TesseractOcr.is_available() else NullOcr()
    if isinstance(engine, NullOcr):
        print("!! tesseract not found - running degraded (every check UNREADABLE)\n")

    timings: list[int] = []
    false_approvals: list[str] = []
    mismatches: list[str] = []
    review_cells = total_cells = 0
    rows = []

    for case in cases:
        app = LabelApplication(**case["application"])
        result = verify(app, engine)
        timings.append(result.elapsed_ms)
        by_id = {c.check_id: c for c in result.checks}

        for check_id, expected in case["expect"].items():
            got = by_id[check_id].outcome.value if check_id in by_id else "MISSING"
            total_cells += 1
            if got == "REVIEW":
                review_cells += 1
            if got != expected:
                mismatches.append(f"{case['case_id']}/{check_id}: expected {expected}, got {got}")
            if expected in ("FAIL", "REVIEW") and got == "PASS":
                false_approvals.append(f"{case['case_id']}/{check_id}")

        flagged = ", ".join(
            f"{c.check_id}:{c.outcome.value}" for c in result.checks if c.needs_agent
        ) or "-"
        rows.append((case["case_id"], result.verdict.value, result.elapsed_ms, flagged))

    bar = "=" * 92
    print(bar)
    print("FIXTURE CORPUS")
    print(bar)
    print(f"{'case':22s} {'verdict':11s} {'ms':>5s}  flagged")
    print("-" * 92)
    for cid, verdict, ms, flagged in rows:
        print(f"{cid:22s} {verdict:11s} {ms:5d}  {flagged}")

    timings.sort()
    p50 = timings[len(timings) // 2]
    p95 = timings[min(len(timings) - 1, max(0, int(round(0.95 * len(timings))) - 1))]

    print()
    print(bar)
    print("GATES")
    print(bar)
    ok = True
    if false_approvals:
        ok = False
        print(f"  false approvals            {len(false_approvals)}  FAIL  {false_approvals}")
    else:
        print("  false approvals            0  PASS")
    if mismatches:
        ok = False
        print(f"  expectation mismatches     {len(mismatches)}  FAIL")
        for m in mismatches:
            print(f"      - {m}")
    else:
        print("  expectation mismatches     0  PASS")
    print(f"  latency p50 / p95          {p50} ms / {p95} ms  "
          f"({'PASS' if p95 < 5000 else 'FAIL'} vs 5000 ms, N-01)")
    print(f"  review rate (not gated)    {review_cells / total_cells:.1%}  "
          f"({review_cells}/{total_cells} checks)")

    for cid in ("clean_spirits", "brand_mismatch", "warning_titlecase"):
        case = next(c for c in cases if c["case_id"] == cid)
        app = LabelApplication(**case["application"])
        _overlay(app, verify(app, engine), os.path.join(OUT, f"overlay_{cid}.png"))
    print(f"\n  overlays -> {os.path.relpath(OUT, REPO_ROOT)}/")

    realistic_ok = _realistic_report(engine)
    boldness_ok = _boldness_report(engine)
    return 0 if ok and p95 < 5000 and realistic_ok and boldness_ok else 1


def _realistic_report(engine) -> bool:
    """The realistic corpus: styled + degraded labels, graded exact/loose."""
    try:
        cases = load_realistic_cases()
    except FileNotFoundError:
        print("\n  (realistic corpus not generated — run `python -m fixtures.realistic`)")
        return True

    bar = "=" * 92
    print()
    print(bar)
    print("REALISTIC CORPUS  (colour / serif / borders / boxed & rotated warnings / photos)")
    print(bar)
    print(f"{'case':24s} {'grade':6s} {'ms':>5s}  {'verdict':10s} flagged")
    print("-" * 92)

    false_appr, exact_mis, timings = [], [], []
    for case in cases:
        app = LabelApplication(**case["application"])
        result = verify(app, engine)
        timings.append(result.elapsed_ms)
        by_id = {c.check_id: c.outcome.value for c in result.checks}
        for cid, exp in case["expect"].items():
            got = by_id.get(cid, "MISSING")
            if exp in ("FAIL", "REVIEW") and got == "PASS":
                false_appr.append(f"{case['case_id']}/{cid}")
            if case["grade"] == "exact" and exp != "MISSING" and got != exp:
                exact_mis.append(f"{case['case_id']}/{cid}: {exp}->{got}")
        flagged = ", ".join(f"{c.check_id}:{c.outcome.value}"
                            for c in result.checks if c.needs_agent) or "-"
        print(f"{case['case_id']:24s} {case['grade']:6s} {result.elapsed_ms:5d}  "
              f"{result.verdict.value:10s} {flagged}")

    timings.sort()
    p95 = timings[min(len(timings) - 1, max(0, int(round(0.95 * len(timings))) - 1))]
    print()
    print(f"  false approvals            {len(false_appr)}  "
          f"{'PASS' if not false_appr else 'FAIL ' + str(false_appr)}")
    print(f"  exact-grade mismatches     {len(exact_mis)}  "
          f"{'PASS' if not exact_mis else 'FAIL'}")
    for m in exact_mis:
        print(f"      - {m}")
    print(f"  latency p95                {p95} ms  ({'PASS' if p95 < 5000 else 'FAIL'})")
    print("  loose-grade cases carry rotation / perspective / low light; a clean field")
    print("  softening to REVIEW/UNREADABLE there is expected (deskew is Phase 1 work).")
    return not false_appr and not exact_mis and p95 < 5000


def _boldness_report(engine) -> bool:
    """W-4 auto-confirm: matched bold / not-bold headers across 6 families."""
    try:
        cases = load_boldness_cases()
    except FileNotFoundError:
        print("\n  (boldness corpus not generated — run `python -m fixtures.boldness`)")
        return True
    from PIL import Image

    bar = "=" * 92
    print()
    print(bar)
    print("W-4 BOLDNESS  (header stroke weight vs the statement's own regular text)")
    print(bar)

    false_pass, auto_fail = [], []
    dec_total = dec_decided = dec_wrong = 0
    for case in cases:
        page = engine.read(case["image"]["path"], 0, "back")
        loc = warning.locate([page])
        outcome, ev = (warning.assess_boldness(loc, Image.open(case["image"]["path"]))
                       if loc else (None, {}))
        val = outcome.value if outcome else "NO-LOC"
        if case["expect_bold"] is False and val == "PASS":
            false_pass.append(case["case_id"])
        if val == "FAIL":
            auto_fail.append(case["case_id"])
        if case["grade"] == "decidable":
            dec_total += 1
            if val in ("PASS", "FAIL"):
                dec_decided += 1
            want = "PASS" if case["expect_bold"] else "REVIEW"
            if val != want:
                dec_wrong += 1

    print(f"  regular headers auto-PASSed   {len(false_pass)}  "
          f"{'PASS' if not false_pass else 'FAIL ' + str(false_pass)}")
    print(f"  headers auto-FAILed           {len(auto_fail)}  "
          f"{'PASS' if not auto_fail else 'FAIL ' + str(auto_fail)}  (W-4 never rejects)")
    print(f"  decidable set correct         {dec_total - dec_wrong}/{dec_total}")
    print(f"  decidable auto-decide rate    {dec_decided}/{dec_total} "
          f"({100 * dec_decided // dec_total}%)   (reported, not gated)")
    print(f"  confirm threshold             {warning._BOLD_CONFIRM_RATIO}x "
          "the regular text's stroke weight")
    return not false_pass and not auto_fail and dec_wrong == 0


if __name__ == "__main__":
    raise SystemExit(main())
