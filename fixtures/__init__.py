"""Generated fixture corpus (design 2.6).

`generate.py` renders synthetic labels to `fixtures/images/` with exact ground
truth in `fixtures/cases.json`. Nothing here is collected from the wild — every
field value is known because we drew it.
"""

from __future__ import annotations

import json
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGES_DIR = os.path.join(REPO_ROOT, "fixtures", "images")
CASES_JSON = os.path.join(REPO_ROOT, "fixtures", "cases.json")
REALISTIC_CASES_JSON = os.path.join(REPO_ROOT, "fixtures", "cases_realistic.json")
BOLDNESS_CASES_JSON = os.path.join(REPO_ROOT, "fixtures", "cases_boldness.json")


def _load(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        cases = json.load(fh)
    for case in cases:
        for img in case["application"]["images"]:
            img["path"] = os.path.join(REPO_ROOT, img["path"])
    return cases


def load_cases() -> list[dict]:
    """The clean generated corpus (fixtures/generate.py), paths repo-rooted."""
    return _load(CASES_JSON)


def load_realistic_cases() -> list[dict]:
    """The realistic corpus (fixtures/realistic.py) — colour, serif faces,
    borders, boxed/rotated warnings, and photo degradation. Cases carry a
    ``grade`` of ``exact`` or ``loose``."""
    return _load(REALISTIC_CASES_JSON)


# --------------------------------------------------------------------------
# Per-field ground truth
#
# Outcome strings alone (PASS / FAIL / …) don't prove the pipeline read the
# *right text* for a field — a broken image or a check pointing at another
# check's line can still produce the expected verdict. So every generated case
# also records, per check, what the label actually says and which image it says
# it on. `tests/test_field_reading.py` asserts against this.
# --------------------------------------------------------------------------

def text_fact(declared: str | None, printed: str | None, images: int | list[int],
              fine_print: str | None = None) -> dict | None:
    """Expected reading of a declared-vs-printed *text* field.

    `images` is every image the value is printed on, not just the first. Brands
    in particular appear twice — the back label repeats the brand as a heading —
    and a check that reads the back copy has read the right text off a real
    display line. Pinning a single index there asserts something the label does
    not actually claim, and turns an OCR wobble on the front into a test failure
    about the wrong thing.

    Returns None when nothing is declared (the check is NOT_DECLARED and has no
    observed text to assert).
    """
    from ttbverify.models import Outcome
    from ttbverify.normalize import compare, punct_norm

    if not declared or not declared.strip():
        return None
    where = [images] if isinstance(images, int) else list(images)
    if printed and compare(declared, printed).outcome in (Outcome.PASS, Outcome.REVIEW):
        return {"status": "matched", "text": printed, "printed": printed,
                "images": where}
    if fine_print and punct_norm(declared) in punct_norm(fine_print):
        return {"status": "only_in_fine_print", "images": where}
    return {"status": "not_found", "text": None, "images": []}


def numeric_facts(declared_abv: str | None, declared_net: str | None,
                  printed_abv: str | None, printed_net: str | None,
                  images: int | list[int]) -> dict:
    """Expected readings for abv / proof / net_contents.

    These come from a *parser* over the label text, so the check reports the
    label's own value even when it disagrees with the application — unlike the
    text fields, which can only ever report a match.
    """
    from ttbverify.parsers import parse_abv, parse_net_contents

    where = [images] if isinstance(images, int) else list(images)
    out: dict[str, dict | None] = {"abv": None, "proof": None, "net_contents": None}
    reading = parse_abv(printed_abv or "")
    if declared_abv and reading.abv is not None:
        out["abv"] = {"status": "matched", "text": f"{reading.abv:g}%",
                      "printed": printed_abv, "images": where}
    if reading.proof is not None:
        out["proof"] = {"status": "matched", "text": f"{reading.proof:g} proof",
                        "printed": printed_abv, "images": where}
    net = parse_net_contents(printed_net or "")
    if declared_net and net.milliliters is not None:
        out["net_contents"] = {"status": "matched",
                               "text": f"{net.quantity:g} {net.unit}",
                               "printed": printed_net, "images": where}
    return out


def audit_corpus(records: list[dict]) -> list[str]:
    """Check every generated label is actually legible before it ships.

    For each case, every field the ground truth says is *printed* on an image
    must be findable in that image's OCR text. Without this a rendering bug —
    a brand name that overflows the label and gets clipped by the border, say —
    ships silently and every downstream test still "passes", because the
    expected verdict can be right for entirely the wrong reason. That happened.

    Returns a list of problems; empty means the corpus is sound. Degraded
    ("photo of a bottle") cases are skipped — unreadable fields are the point.
    """
    from ttbverify.normalize import punct_norm
    from ttbverify.ocr import TesseractOcr

    if not TesseractOcr.is_available():
        return ["tesseract not installed — corpus not audited"]
    engine = TesseractOcr()
    problems: list[str] = []

    for case in records:
        if case.get("degraded"):
            continue
        facts = case.get("expect_observed") or {}
        images = case["application"]["images"]
        lines_by_image: dict[int, list[str]] = {}
        for idx, ref in enumerate(images):
            path = ref["path"]
            if not os.path.isabs(path):
                path = os.path.join(REPO_ROOT, path)
            page = engine.read(path, idx, ref.get("role"))
            lines_by_image[idx] = [punct_norm(line) for line in page.text.splitlines()]

        for check_id, fact in facts.items():
            if not fact or fact.get("status") != "matched":
                continue
            # audit the *raw* string the label prints, not the normalized form
            # the check reports back ("12 fl oz" on the label vs "12 floz" parsed)
            printed = fact.get("printed") or fact.get("text")
            if not printed:
                continue
            want = punct_norm(printed)
            found = any(
                _legible(check_id, want, lines_by_image.get(idx, []))
                for idx in fact.get("images") or [0]
            )
            if not found:
                problems.append(
                    f"{case['case_id']}: {check_id} prints {printed!r} on image "
                    f"{fact.get('images')}, but it isn't legible there")
    return problems


def _legible(check_id: str, want: str, lines: list[str]) -> bool:
    """Is `want` readable on this image *the way its check will look for it*?

    Display fields (brand, class/type) must be a line of their own — that is the
    admissibility rule the engine applies (design 3.2), and auditing anything
    looser lets a real defect through: a brand clipped off the edge of the label
    still appears inside the bottler statement further down, so a
    "is this string anywhere on the image" check passes a label whose brand
    Tesseract never saw. That is the exact failure this audit exists to catch.

    Everything else may sit inside a longer line — a bottler statement is a
    sentence, and "40% Alc./Vol." is printed inside "40% ALC./VOL. (80 PROOF)".
    """
    if check_id in ("brand", "class_type"):
        return any(want == line for line in lines)
    return any(want in line for line in lines)


def load_boldness_cases() -> list[dict]:
    """Matched bold / not-bold warning-header cases (fixtures/boldness.py) for
    calibrating and gating W-4. Each has a single image."""
    with open(BOLDNESS_CASES_JSON, encoding="utf-8") as fh:
        cases = json.load(fh)
    for case in cases:
        case["image"]["path"] = os.path.join(REPO_ROOT, case["image"]["path"])
    return cases


# --------------------------------------------------------------------------
# cassette scenario (CLAUDE.md 2.9 — the recorded vision path)
# --------------------------------------------------------------------------

CASSETTE_IMAGES = os.path.join(os.path.dirname(__file__), "cassettes", "images")


def cassette_application():
    """The label the committed vision cassettes were recorded against.

    Defined here rather than in either the test or the recorder so the two cannot
    drift: the cassette key covers the prompt, the schema *and* the image bytes,
    so a recorder that built a slightly different application would produce
    recordings that never match at replay.

    The images are frozen copies under `fixtures/cassettes/images/`, deliberately
    not the generated corpus — regenerating `r12_lowlight` would otherwise
    invalidate every recording.
    """
    from ttbverify.models import Commodity, LabelApplication

    return LabelApplication(
        serial_number="200012",
        ttb_id="24RIC01000012",
        brand_name="RUSTY ANCHOR",
        class_type="Aged Caribbean Rum",
        commodity=Commodity.SPIRITS,
        alcohol_content="40% Alc./Vol.",
        net_contents="750 mL",
        applicant_name="Rusty Anchor Spirits",
        images=[
            {"path": os.path.join(CASSETTE_IMAGES, "lowlight_front.jpg"),
             "role": "front"},
            {"path": os.path.join(CASSETTE_IMAGES, "lowlight_back.jpg"),
             "role": "back"},
        ],
    )
