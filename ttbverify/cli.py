"""Phase 0 command-line entry point.

    python -m ttbverify application.json
    python -m ttbverify application.json --json
    python -m ttbverify --demo clean_spirits

`application.json` is a single object in the canonical schema (design 2.2) — the
same shape as the `"application"` block in `fixtures/cases.json`:

    {
      "serial_number": "100001",
      "brand_name": "OLD TOM DISTILLERY",
      "class_type": "Kentucky Straight Bourbon Whiskey",
      "commodity": "spirits",
      "alcohol_content": "45% Alc./Vol.",
      "net_contents": "750 mL",
      "applicant_name": "Old Tom Distillery, LLC",
      "images": [{"path": "front.png", "role": "front"},
                 {"path": "back.png", "role": "back"}]
    }

Image paths are resolved relative to the JSON file's directory.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from ttbverify.models import LabelApplication, Outcome, OUTCOME_LABEL
from ttbverify.ocr import NullOcr, TesseractOcr
from ttbverify.pipeline import verify

_MARK = {
    Outcome.PASS: "[ok]  ",
    Outcome.REVIEW: "[?]   ",
    Outcome.FAIL: "[X]   ",
    Outcome.UNREADABLE: "[--]  ",
    Outcome.NOT_DECLARED: "[n/a] ",
}


def _load_application(path: str) -> LabelApplication:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if "application" in data:  # allow a whole fixture record too
        data = data["application"]
    base = os.path.dirname(os.path.abspath(path))
    for img in data.get("images", []):
        if isinstance(img, dict) and not os.path.isabs(img["path"]):
            img["path"] = os.path.join(base, img["path"])
        elif isinstance(img, str) and not os.path.isabs(img):
            data["images"][data["images"].index(img)] = os.path.join(base, img)
    return LabelApplication(**data)


def _demo_application(case_id: str) -> LabelApplication:
    from fixtures import load_cases

    for case in load_cases():
        if case["case_id"] == case_id:
            return LabelApplication(**case["application"])
    raise SystemExit(f"no demo case '{case_id}'. See fixtures/cases.json for ids.")


def _print_human(result) -> None:
    print()
    print(f"  {result.summary_line}")
    print(f"  verdict: {result.verdict.value}   "
          f"({result.elapsed_ms} ms; stages {result.stage_ms})")
    if not result.ocr_available:
        print("  NOTE: OCR unavailable — ran in degraded mode, nothing auto-approved.")
    print()
    for c in result.checks:
        print(f"  {_MARK[c.outcome]}{c.field_label:<28} {OUTCOME_LABEL[c.outcome]}")
        if c.detail:
            print(f"        {c.detail}")
        if c.check_id == "warn_text" and c.evidence.get("diff"):
            for d in c.evidence["diff"][:8]:
                print(f"          - {d}")
    if result.notes:
        print()
        for n in result.notes:
            print(f"  ! {n}")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ttbverify", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("application", nargs="?", help="path to an application JSON file")
    src.add_argument("--demo", metavar="CASE_ID",
                     help="run a fixture case from fixtures/cases.json")
    parser.add_argument("--json", action="store_true", help="emit result as JSON")
    parser.add_argument("--no-ocr", action="store_true",
                        help="force the degraded NullOcr path")
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    app = _demo_application(args.demo) if args.demo else _load_application(args.application)

    if args.no_ocr:
        engine = NullOcr()
    elif TesseractOcr.is_available():
        engine = TesseractOcr()
    else:
        print("tesseract not found — using the degraded NullOcr path.", file=sys.stderr)
        engine = NullOcr()

    result = verify(app, engine)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        _print_human(result)

    return 0 if result.verdict in (Outcome.PASS, Outcome.NOT_DECLARED) else 1


if __name__ == "__main__":
    raise SystemExit(main())
