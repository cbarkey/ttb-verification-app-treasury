"""Health warning statement checks — W-1 through W-4 (design 2.3, 3.3, 3.4).

Reference text is 27 CFR 16.21, verbatim. This is the one field where the system
is deliberately *unforgiving* about wording and casing — but not so brittle that
ordinary OCR character noise triggers a false rejection.

  W-1 Presence   statement located on some image                -> else FAIL
  W-2 Wording    word-by-word vs reference, two bands:
                   close-but-not-equal token -> probable OCR noise -> REVIEW
                   genuinely different token -> FAIL + word diff
  W-3 Casing     "GOVERNMENT WARNING" must be uppercase          -> else FAIL
  W-4 Boldness   auto-PASS only when the header is confidently heavier than the
                 statement's own regular-weight text; otherwise REVIEW with the
                 measurement as evidence. Never auto-FAIL. (see assess_boldness)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from PIL import Image, ImageFilter

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

# How far past the "GOVERNMENT WARNING" anchor to gather tokens — a little slack
# for OCR splitting a word in two, but not so much that whatever the label prints
# *after* the warning (a barcode number, a URL, marketing copy) gets pulled in.
# Trailing tokens with no reference counterpart are dropped in compare_wording.
_BLOCK_SPAN = len(REFERENCE_TOKENS) + 6


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

    n_ref = len(ref)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        # Anything happening only on the `got` side at or past the end of the
        # reference is text that comes *after* the warning statement (a barcode
        # number, a URL, a tagline). Not a wording violation — stop here.
        trailing = i1 >= n_ref
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
                elif not trailing:
                    diff.append({"pos": i1 + k, "expected": None, "got": g,
                                 "kind": "extra"})
        elif tag == "delete":
            for k in range(i1, i2):
                diff.append({"pos": k, "expected": ref[k], "got": None, "kind": "missing"})
        elif tag == "insert" and not trailing:
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


# --- W-4 boldness -------------------------------------------------------------
#
# Design 3.4 warned off thresholding an *absolute* ink-density figure, because
# capital letters read denser than lowercase regardless of weight. This does
# something different and confound-free: it asks whether "GOVERNMENT WARNING" is
# *heavier than the regular-weight remainder of the same statement* — same font
# family, same size, guaranteed present. The estimator is a stroke thickness
# (2 * ink area / ink perimeter), normalized by glyph height, computed on a 4x
# upscale so a 1-2 px stroke isn't lost to quantization.
#
# Calibrated on `fixtures/boldness.py` (6 families x regular/bold x 2 sizes x
# clean/degraded + adversarial): regular headers land at 1.29-1.46x the body,
# genuine bold at 1.64x and up. Auto-confirm only well clear of that gap, and
# only ever PASS — never auto-FAIL. Everything short of confident goes to REVIEW,
# with the measurement shown as evidence.

_BOLD_CONFIRM_RATIO = 1.55
_BOLD_MIN_HEADER_PX = 8       # header box height (original px) below which we can't measure
_BOLD_UPSCALE = 4


def _otsu(gray: Image.Image) -> int:
    hist = gray.histogram()
    total = sum(hist)
    if not total:
        return 127
    sum_all = sum(i * hist[i] for i in range(256))
    sum_b = w_b = 0.0
    best_var, thr = 0.0, 127
    for i in range(256):
        w_b += hist[i]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += i * hist[i]
        m_b = sum_b / w_b
        m_f = (sum_all - sum_b) / w_f
        var = w_b * w_f * (m_b - m_f) ** 2
        if var > best_var:
            best_var, thr = var, i
    return thr


def _strip_thickness(image: Image.Image, box: BoundingBox) -> float | None:
    """Height-normalized stroke thickness of the text inside `box`.

    Handles light-on-dark labels: whichever side of the Otsu split is the
    minority is taken to be the ink.
    """
    pad = 3
    left, top = max(0, box.left - pad), max(0, box.top - pad)
    right = min(image.width, box.right + pad)
    bottom = min(image.height, box.bottom + pad)
    if right - left < 5 or bottom - top < 5:
        return None
    gray = image.convert("L").crop((left, top, right, bottom)).resize(
        ((right - left) * _BOLD_UPSCALE, (bottom - top) * _BOLD_UPSCALE), Image.LANCZOS)
    thr = _otsu(gray)
    hist = gray.histogram()
    dark = sum(hist[: thr + 1])
    light = sum(hist[thr + 1:])
    ink_is_dark = dark <= light          # text is the minority region
    binary = gray.point(
        lambda p, t=thr: 255 if ((p <= t) == ink_is_dark) else 0
    )
    area = binary.histogram()[255]
    if area < 200:
        return None
    interior = binary.filter(ImageFilter.MinFilter(3)).histogram()[255]
    boundary = max(1, area - interior)
    inked = binary.getbbox()
    if not inked:
        return None
    ink_height = inked[3] - inked[1]
    return (2.0 * area / boundary) / ink_height if ink_height else None


def assess_boldness(loc: WarningLocation, image) -> tuple[Outcome, dict]:
    """PASS only when the header is confidently heavier than the regular text;
    REVIEW (with the numbers) otherwise. Never auto-FAIL."""
    if image is None:
        return Outcome.REVIEW, {"reason": "No image available — confirm boldness from the label."}
    header = loc.anchor_words
    if not header or loc.anchor_box.height < _BOLD_MIN_HEADER_PX:
        return Outcome.REVIEW, {
            "reason": "Header text too small to measure — confirm from the crop."}

    body = [w for w in loc.words if w not in header
            and sum(ch.isalpha() for ch in w.text) >= 3]
    if len(body) < 3:
        return Outcome.REVIEW, {
            "reason": "No regular-weight text to compare against — confirm from the crop."}
    first_top = body[0].box.top
    body_line = [w for w in body if abs(w.box.top - first_top) < body[0].box.height][:12]

    h_thick = _strip_thickness(image, BoundingBox.enclosing(w.box for w in header))
    b_thick = _strip_thickness(image, BoundingBox.enclosing(w.box for w in body_line))
    if not h_thick or not b_thick:
        return Outcome.REVIEW, {
            "reason": "Couldn't measure stroke weight cleanly — confirm from the crop."}

    ratio = h_thick / b_thick
    ev = {"header_stroke": round(h_thick, 4), "body_stroke": round(b_thick, 4),
          "weight_ratio": round(ratio, 2), "confirm_at": _BOLD_CONFIRM_RATIO}
    if ratio >= _BOLD_CONFIRM_RATIO:
        ev["reason"] = (f"'GOVERNMENT WARNING' measures {ratio:.2f}x the stroke weight of "
                        "the statement's regular text — confidently bold.")
        return Outcome.PASS, ev
    ev["reason"] = (f"'GOVERNMENT WARNING' is {ratio:.2f}x the regular text; auto-confirm "
                    f"needs {_BOLD_CONFIRM_RATIO}x. Confirm boldness from the crop.")
    return Outcome.REVIEW, ev


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

    common = {"image_index": loc.page_index, "image_role": loc.page_role}

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

    # W-4 boldness — auto-confirm the confidently-bold case, REVIEW the rest.
    w4_outcome, w4_ev = assess_boldness(loc, images.get(loc.page_index))
    w4 = CheckResult(
        "warn_bold", _CHECK_LABELS["warn_bold"], w4_outcome,
        box=loc.anchor_box, detail=w4_ev.pop("reason"),
        evidence=w4_ev, **common,
    )

    return [w1, w2, w3, w4]


_CHECK_LABELS = {
    "warn_present": "Health warning present",
    "warn_text": "Health warning wording",
    "warn_case": "Health warning capitalization",
    "warn_bold": "Health warning bold header",
}
