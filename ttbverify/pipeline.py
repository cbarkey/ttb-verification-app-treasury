"""Per-label orchestration: ingest -> deskew+OCR -> rules + warning -> [vision] -> result.

Stage timings are measured and returned (N-03) — the UI shows real latency to a
team that was burned by a slow vendor once already.

The vision fallback at the end is the only model call on this path, it is
conditional on a field still being unreadable, and its output is capped at
`REVIEW`. See `_apply_vision_fallback` and DESIGN.md 2.9.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterable

from PIL import Image

from ttbverify import rules, warning
from ttbverify.ai.client import AiClient, NullAi
from ttbverify.ai.vision import Reading, read_fields
from ttbverify.models import CheckResult, LabelApplication, Outcome, VerificationResult
from ttbverify.normalize import compare
from ttbverify.ocr import NullOcr, OcrEngine, OcrPage
from ttbverify.parsers import parse_abv, parse_net_contents

# check_id -> the LabelApplication attribute holding the declared value. Only
# fields with something to compare against are worth a model call.
_VISION_FIELDS = {
    "brand": "brand_name",
    "class_type": "class_type",
    "producer": "applicant_name",
    "origin": "origin",
    "abv": "alcohol_content",
    "net_contents": "net_contents",
}

# What the review row says when a reading came from the model rather than OCR.
VISION_ATTRIBUTION = "read by vision model — confirm"


def _now_ms() -> float:
    return time.perf_counter() * 1000.0


def verify(
    app: LabelApplication,
    ocr: OcrEngine | None = None,
    *,
    ai: AiClient | None = None,
    timeout_ms: float | None = 5000.0,
) -> VerificationResult:
    ocr = ocr or NullOcr()
    ai = ai or NullAi()
    start = _now_ms()
    stage_ms: dict[str, float] = {}
    notes: list[str] = []

    # --- ingest + OCR ---
    t = _now_ms()
    pages: list[OcrPage] = []
    for i, ref in enumerate(app.images):
        name = os.path.basename(ref.path) or ref.path
        if not os.path.isfile(ref.path):
            notes.append(f"Couldn't open image '{name}' ({ref.role or 'label'}) — file not found.")
            pages.append(OcrPage(words=[], width=0, height=0, index=i, role=ref.role))
            continue
        try:
            pages.append(ocr.read(ref.path, index=i, role=ref.role))
        except Exception as exc:  # noqa: BLE001 — one bad image must not sink the label
            notes.append(f"Couldn't read image '{name}' ({ref.role or 'label'}): {exc}")
            pages.append(OcrPage(words=[], width=0, height=0, index=i, role=ref.role))
    stage_ms["ocr"] = _now_ms() - t

    corrected = [p for p in pages if p.correction.applied]
    if corrected:
        notes.append(
            "Straightened "
            + ("1 image" if len(corrected) == 1 else f"{len(corrected)} images")
            + " before reading ("
            + "; ".join(p.correction.describe() for p in corrected)
            + ")."
        )

    ocr_available = any(p.engine != "null" for p in pages)
    if not ocr_available:
        notes.append("OCR engine unavailable — ran in degraded mode.")

    # --- rules + warning ---
    t = _now_ms()
    checks: list[CheckResult] = rules.evaluate(app, pages, ocr_available=ocr_available)
    stage_ms["rules"] = _now_ms() - t

    t = _now_ms()
    pil_images = _load_images(app)
    checks.extend(
        warning.evaluate(pages, images=pil_images, ocr_available=ocr_available)
    )
    stage_ms["warning"] = _now_ms() - t

    # --- conditional vision fallback (2.9 use A) ---
    over_budget = timeout_ms is not None and (_now_ms() - start) > timeout_ms
    unreadable = [c for c in checks if c.outcome is Outcome.UNREADABLE]
    if unreadable and ai.available and not over_budget:
        t = _now_ms()
        checks = _apply_vision_fallback(app, checks, ai, notes)
        stage_ms["vision"] = _now_ms() - t
    elif unreadable and ai.available and over_budget:
        notes.append("Skipped the vision fallback — already over the latency budget.")

    elapsed = _now_ms() - start
    if timeout_ms is not None and elapsed > timeout_ms:
        notes.append(f"Processing took {elapsed:.0f} ms (budget {timeout_ms:.0f} ms).")

    return VerificationResult(
        application_key=app.key,
        checks=checks,
        elapsed_ms=round(elapsed),
        stage_ms={k: round(v, 1) for k, v in stage_ms.items()},
        ocr_available=ocr_available,
        notes=notes,
    )


def verify_batch(
    apps: Iterable[LabelApplication],
    ocr: OcrEngine | None = None,
    *,
    ai: AiClient | None = None,
    timeout_ms: float | None = 5000.0,
):
    """Yield (application_key, VerificationResult | Exception) as each completes.

    Per-item failures are isolated (design 3.7) — a corrupt image surfaces as that
    item's own error, everything else finishes.
    """
    for app in apps:
        try:
            yield app.key, verify(app, ocr, ai=ai, timeout_ms=timeout_ms)
        except Exception as exc:  # noqa: BLE001 - isolation is the point
            yield app.key, exc


def _load_images(app: LabelApplication) -> dict[int, Image.Image]:
    """Decode the images into memory, releasing the file handles deterministically.

    `Image.open` is lazy: it holds the file open until something forces a decode.
    Whether that happens depends on the label — the W-4 check crops the warning
    block, which loads the image, but on a label where the warning is never
    located nothing does. The handle is then released whenever the object is
    collected, which under CPython refcounting is usually immediately on return,
    and "usually" is doing real work in that sentence. The service verifies
    inside a `TemporaryDirectory`, and on Windows an open handle makes the
    *cleanup* fail, which surfaces as a 500 a long way from the cause.

    So decode eagerly and copy out: the handle is closed before this returns,
    on every path, regardless of what the rest of the pipeline happens to touch.
    Costs a few MB per label for one request.

    (Honest note: this was written after a 500 of exactly that shape, but the
    leak could not be reproduced in isolation — see the tests. Treat it as
    removing a class of timing-dependent failure, not as a diagnosed fix.)
    """
    out: dict[int, Image.Image] = {}
    for i, ref in enumerate(app.images):
        try:
            with Image.open(ref.path) as im:
                out[i] = im.copy()
        except OSError:
            continue
    return out


# --------------------------------------------------------------------------
# vision fallback
# --------------------------------------------------------------------------

def _apply_vision_fallback(
    app: LabelApplication,
    checks: list[CheckResult],
    ai: AiClient,
    notes: list[str],
) -> list[CheckResult]:
    """Retry still-unreadable fields with a vision model, capped at REVIEW.

    **The cap is the entire safety argument and it is unconditional** (DESIGN.md
    2.9). A model-sourced reading becomes `REVIEW` — never `PASS`, and never
    `FAIL` either — whatever the comparison ladder concludes about it. The
    comparison still runs, because "the label appears to read `STONE'S THROW`,
    which matches after ignoring capitalization" is a far more useful thing to
    hand an agent than a bare string. But its outcome is advisory.

    Two consequences worth being explicit about:

      * "zero false approvals" stays a property of the deterministic system. It
        is gated in CI against corpora that can actually be re-run; a
        nondeterministic component able to mint a PASS would move a proven
        property into the merely-likely column.
      * whether Marcus's firewall let the call through changes the *evidence*, not
        the *verdict class*. With a key: REVIEW plus a reading. Without: still
        unreadable. Both go to a human; neither approves.
    """
    wanted = {
        c.check_id: getattr(app, _VISION_FIELDS[c.check_id])
        for c in checks
        if c.outcome is Outcome.UNREADABLE
        and c.check_id in _VISION_FIELDS
        and getattr(app, _VISION_FIELDS[c.check_id])
    }
    if not wanted:
        return checks

    readings: dict[str, Reading] = {}
    for index, ref in enumerate(app.images):
        outstanding = [c for c in wanted if c not in readings]
        if not outstanding:
            break
        found, error = read_fields(ai, ref.path, outstanding, image_index=index)
        if error:
            # Firewalled, timed out, malformed — not an error condition here
            # (design 2.4 failure table). The deterministic result stands.
            notes.append(f"Vision fallback unavailable: {error}")
            return checks
        for reading in found:
            readings.setdefault(reading.check_id, reading)

    if not readings:
        return checks
    notes.append(
        f"A vision model read {len(readings)} field(s) OCR could not. "
        "Model readings are always routed to review, never approved automatically."
    )

    role_by_index = {i: ref.role for i, ref in enumerate(app.images)}
    out: list[CheckResult] = []
    for check in checks:
        reading = readings.get(check.check_id)
        if reading is None or check.outcome is not Outcome.UNREADABLE:
            out.append(check)
            continue
        out.append(_review_from_reading(check, wanted[check.check_id], reading,
                                        role_by_index.get(reading.image_index)))
    return out


def _review_from_reading(check: CheckResult, declared: str, reading: Reading,
                         image_role: str | None) -> CheckResult:
    detail = f"{_compare_detail(check.check_id, declared, reading.text)} " \
             f"({VISION_ATTRIBUTION})"
    return CheckResult(
        check.check_id,
        check.field_label,
        Outcome.REVIEW,  # the cap — see _apply_vision_fallback
        declared=declared,
        observed=reading.text,
        detail=detail,
        tier="vision",
        box=None,  # the model reports text, not pixels; no overlay is honest here
        image_index=reading.image_index,
        image_role=image_role,
        evidence={
            "source": "vision_model",
            "model": reading.model,
            "model_confidence": round(reading.confidence, 3),
            "capped_at_review": True,
        },
    )


def _compare_detail(check_id: str, declared: str, observed: str) -> str:
    """What the deterministic rule *would* have said about this reading.

    Advisory: it explains the reading to the agent, it does not set the outcome.
    """
    if check_id == "abv":
        want, got = parse_abv(declared), parse_abv(observed)
        if want.abv is not None and got.abv is not None:
            verb = "matches" if abs(want.abv - got.abv) <= rules.ABV_EXACT_EPS \
                else "differs from"
            return (f"Label appears to read {got.abv:g}% — {verb} the declared "
                    f"{want.abv:g}%")
        return f"Label appears to read '{observed}'"
    if check_id == "net_contents":
        want, got = parse_net_contents(declared), parse_net_contents(observed)
        if want.milliliters and got.milliliters:
            same = abs(want.milliliters - got.milliliters) / want.milliliters \
                <= rules.NET_EXACT_REL
            verb = "matches" if same else "differs from"
            return (f"Label appears to read {observed} — {verb} the declared "
                    f"{declared}")
        return f"Label appears to read '{observed}'"
    return f"Label appears to read '{observed}' — {compare(declared, observed).detail}"
