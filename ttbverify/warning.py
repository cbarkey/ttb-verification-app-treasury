"""Health warning statement checks — W-1 through W-4 (design 2.3, 3.3, 3.4).

Reference text is 27 CFR 16.21, verbatim. This is the one field where the system
is deliberately *unforgiving* about wording and casing — but not so brittle that
ordinary OCR character noise triggers a false rejection.

  W-1 Presence   statement located on some image                -> else FAIL
  W-2 Wording    word-by-word vs reference, two bands:
                   close-but-not-equal token -> probable OCR noise -> REVIEW
                   genuinely different token -> FAIL + word diff
  W-3 Casing     "GOVERNMENT WARNING" must be uppercase          -> else FAIL
  W-4 Boldness   never auto-decided -> always REVIEW, with a crop + a density
                 number shown purely as evidence (design 3.4)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ttbverify.models import BoundingBox, CheckResult, Outcome
from ttbverify.normalize import similarity
from ttbverify.ocr import OcrPage, OcrWord

REFERENCE_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not "
    "drink alcoholic beverages during pregnancy because of the risk of birth "
    "defects. (2) Consumption of alcoholic beverages impairs your ability to "
    "drive a car or operate machinery, and may cause health problems."
)

REFERENCE_TOKENS = REFERENCE_WARNING.split()

# A label token this similar to its reference token (but not equal) is treated as
# OCR noise, not a rewording (design 3.3). Tuned to "a character or two off".
_OCR_NOISE_FLOOR = 0.75

# How far past the "GOVERNMENT WARNING" anchor to gather tokens, as a multiple of
# the reference length — generous enough to catch trailing words, bounded so a
# whole back label isn't swallowed.
_BLOCK_SPAN = len(REFERENCE_TOKENS) + 12


def _cmp_token(tok: str) -> str:
    """Casefold + strip surrounding punctuation. Casing is W-3's concern, not W-2's."""
    return re.sub(r"^\W+|\W+$", "", tok).casefold()


@dataclass
class WarningLocation:
    page_index: int
    page_role: str | None
    words: list[OcrWord]
    anchor_box: BoundingBox        # box around "GOVERNMENT WARNING"
    block_box: BoundingBox         # box around the whole located statement

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def anchor_words(self) -> list[OcrWord]:
        """The one or two words forming the 'GOVERNMENT WARNING' header."""
        out: list[OcrWord] = []
        for w in self.words[:3]:
            stripped = _cmp_token(w.text)
            if stripped.startswith("government") or stripped.startswith("warning"):
                out.append(w)
            if len(out) == 2:
                break
        return out


def locate(pages: list[OcrPage]) -> WarningLocation | None:
    """Find the warning by anchoring on consecutive GOVERNMENT + WARNING tokens.

    Searches every image (F-08 — the warning usually lives on the back label).
    """
    for page in pages:
        words = page.words
        for i in range(len(words) - 1):
            a, b = _cmp_token(words[i].text), _cmp_token(words[i + 1].text)
            merged = _cmp_token(words[i].text)
            hit = (a.startswith("government") and b.startswith("warning")) or (
                merged.startswith("governmentwarning")
            )
            if not hit:
                continue
            span = words[i : i + _BLOCK_SPAN]
            anchor = span[:2]
            return WarningLocation(
                page_index=page.index,
                page_role=page.role,
                words=span,
                anchor_box=BoundingBox.enclosing(w.box for w in anchor),
                block_box=BoundingBox.enclosing(w.box for w in span),
            )
    return None


# --- W-2 wording -------------------------------------------------------------

@dataclass
class WordingReport:
    outcome: Outcome
    diff: list[dict]          # per-position: {pos, expected, got, kind}
    noise_positions: list[int]

    @property
    def hard_mismatches(self) -> list[dict]:
        return [d for d in self.diff if d["kind"] in ("substituted", "missing", "extra")]


def compare_wording(located_tokens: list[str]) -> WordingReport:
    """Two-band word comparison against the reference (design 3.3).

    Uses difflib to align, so an omitted or inserted word shows up as exactly
    that rather than cascading every following position into a mismatch.
    """
    from difflib import SequenceMatcher

    ref = [_cmp_token(t) for t in REFERENCE_TOKENS]
    got = [_cmp_token(t) for t in located_tokens if _cmp_token(t)]

    diff: list[dict] = []
    noise_positions: list[int] = []
    sm = SequenceMatcher(a=ref, b=got, autojunk=False)

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace":
            for k in range(max(i2 - i1, j2 - j1)):
                r = ref[i1 + k] if i1 + k < i2 else None
                g = got[j1 + k] if j1 + k < j2 else None
                if r is not None and g is not None:
                    sim = similarity(r, g)
                    if sim >= _OCR_NOISE_FLOOR:
                        noise_positions.append(i1 + k)
                        diff.append({"pos": i1 + k, "expected": r, "got": g,
                                     "kind": "ocr_noise", "similarity": round(sim, 2)})
                    else:
                        diff.append({"pos": i1 + k, "expected": r, "got": g,
                                     "kind": "substituted"})
                elif r is not None:
                    diff.append({"pos": i1 + k, "expected": r, "got": None,
                                 "kind": "missing"})
                else:
                    diff.append({"pos": i1 + k, "expected": None, "got": g,
                                 "kind": "extra"})
        elif tag == "delete":
            for k in range(i1, i2):
                diff.append({"pos": k, "expected": ref[k], "got": None, "kind": "missing"})
        elif tag == "insert":
            for k in range(j1, j2):
                diff.append({"pos": i1, "expected": None, "got": got[k], "kind": "extra"})

    hard = [d for d in diff if d["kind"] in ("substituted", "missing", "extra")]
    if hard:
        outcome = Outcome.FAIL
    elif noise_positions:
        outcome = Outcome.REVIEW
    else:
        outcome = Outcome.PASS
    return WordingReport(outcome, diff, noise_positions)


# --- W-4 boldness evidence -------------------------------------------------

def _dark_ratio(image, box: BoundingBox) -> float | None:
    """Fraction of near-black pixels in a box. Evidence only — never a verdict."""
    if image is None or box is None or box.area == 0:
        return None
    crop = image.convert("L").crop((box.left, box.top, box.right, box.bottom))
    hist = crop.histogram()
    dark = sum(hist[:96])
    total = sum(hist)
    return dark / total if total else None


# --- top-level evaluation -------------------------------------------------

def evaluate(pages: list[OcrPage], images: dict | None = None,
             ocr_available: bool = True) -> list[CheckResult]:
    """Return the W-1..W-4 CheckResults for an application's images."""
    images = images or {}

    if not ocr_available:
        reason = "OCR unavailable — warning statement not read"
        return [
            CheckResult(cid, label, Outcome.UNREADABLE, detail=reason)
            for cid, label in _CHECK_LABELS.items()
        ]

    loc = locate(pages)

    if loc is None:
        # W-1 is the mandatory-element failure; the rest can't be performed on a
        # statement that isn't there. Never PASS (governing principle).
        return [
            CheckResult("warn_present", _CHECK_LABELS["warn_present"], Outcome.FAIL,
                        detail="No health warning statement found on any image."),
            CheckResult("warn_text", _CHECK_LABELS["warn_text"], Outcome.FAIL,
                        detail="No statement located to compare."),
            CheckResult("warn_case", _CHECK_LABELS["warn_case"], Outcome.FAIL,
                        detail="No statement located to check casing."),
            CheckResult("warn_bold", _CHECK_LABELS["warn_bold"], Outcome.FAIL,
                        detail="No statement located to review for boldness."),
        ]

    common = dict(image_index=loc.page_index, image_role=loc.page_role)

    # W-1 presence
    w1 = CheckResult("warn_present", _CHECK_LABELS["warn_present"], Outcome.PASS,
                     observed=loc.text, box=loc.block_box,
                     detail=f"Warning statement found on the {loc.page_role or 'label'} image.",
                     **common)

    # W-2 wording
    report = compare_wording([w.text for w in loc.words])
    if report.outcome is Outcome.PASS:
        w2_detail = "Wording matches the statutory text."
    elif report.outcome is Outcome.REVIEW:
        w2_detail = (
            f"{len(report.noise_positions)} word(s) look like OCR misreads, not "
            "rewording — confirm against the crop."
        )
    else:
        changed = ", ".join(
            f"'{d['expected']}'->'{d['got']}'" if d["kind"] == "substituted"
            else f"missing '{d['expected']}'" if d["kind"] == "missing"
            else f"extra '{d['got']}'"
            for d in report.hard_mismatches[:5]
        )
        w2_detail = f"Wording differs from the statutory text: {changed}."
    w2 = CheckResult("warn_text", _CHECK_LABELS["warn_text"], report.outcome,
                     declared=REFERENCE_WARNING, observed=loc.text,
                     box=loc.block_box, detail=w2_detail,
                     evidence={"diff": report.diff}, **common)

    # W-3 casing
    anchor = loc.anchor_words
    anchor_text = " ".join(w.text for w in anchor)
    letters = re.sub(r"[^A-Za-z]", "", anchor_text)
    is_upper = bool(letters) and letters.isupper()
    w3 = CheckResult(
        "warn_case", _CHECK_LABELS["warn_case"],
        Outcome.PASS if is_upper else Outcome.FAIL,
        observed=anchor_text or None,
        box=loc.anchor_box,
        detail=("'GOVERNMENT WARNING' is uppercase." if is_upper
                else f"'GOVERNMENT WARNING' must be all caps; label shows '{anchor_text}'."),
        **common,
    )

    # W-4 boldness — always REVIEW (design 3.4)
    ratio = _dark_ratio(images.get(loc.page_index), loc.anchor_box)
    body_ratio = _dark_ratio(images.get(loc.page_index), loc.block_box)
    evidence = {"header_dark_ratio": round(ratio, 3) if ratio is not None else None,
                "block_dark_ratio": round(body_ratio, 3) if body_ratio is not None else None}
    w4 = CheckResult(
        "warn_bold", _CHECK_LABELS["warn_bold"], Outcome.REVIEW,
        box=loc.anchor_box,
        detail="Boldness can't be judged reliably by machine — confirm from the crop.",
        evidence=evidence, **common,
    )

    return [w1, w2, w3, w4]


_CHECK_LABELS = {
    "warn_present": "Health warning present",
    "warn_text": "Health warning wording",
    "warn_case": "Health warning capitalization",
    "warn_bold": "Health warning bold header",
}
