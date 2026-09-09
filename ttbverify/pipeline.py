"""Per-label orchestration: ingest -> OCR -> rules + warning -> [VLM] -> result.

Stage timings are measured and returned (N-03) — the UI shows real latency to a
team that was burned by a slow vendor once already.
"""

from __future__ import annotations

import os
import time
from typing import Iterable

from PIL import Image

from ttbverify import warning
from ttbverify import rules
from ttbverify.models import CheckResult, LabelApplication, Outcome, VerificationResult
from ttbverify.normalize import compare
from ttbverify.ocr import NullOcr, OcrEngine, OcrPage
from ttbverify.vlm import NullVlm, VlmClient

# Field checks a vision fallback can meaningfully retry (text fields only).
_VLM_RETRYABLE = {
    "brand": "brand_name",
    "class_type": "class_type",
    "producer": "applicant_name",
    "origin": "origin",
}


def _now_ms() -> float:
    return time.perf_counter() * 1000.0


def verify(
    app: LabelApplication,
    ocr: OcrEngine | None = None,
    *,
    vlm: VlmClient | None = None,
    timeout_ms: float | None = 5000.0,
) -> VerificationResult:
    ocr = ocr or NullOcr()
    vlm = vlm or NullVlm()
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
        except Exception as exc:  # one bad image must not sink the label
            notes.append(f"Couldn't read image '{name}' ({ref.role or 'label'}): {exc}")
            pages.append(OcrPage(words=[], width=0, height=0, index=i, role=ref.role))
    stage_ms["ocr"] = _now_ms() - t

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

    # --- conditional VLM fallback ---
    over_budget = timeout_ms is not None and (_now_ms() - start) > timeout_ms
    unreadable = [c for c in checks if c.outcome is Outcome.UNREADABLE]
    if unreadable and vlm.available and not over_budget:
        t = _now_ms()
        checks = _apply_vlm_fallback(app, checks, vlm, notes)
        stage_ms["vlm"] = _now_ms() - t
    elif unreadable and vlm.available and over_budget:
        notes.append("Skipped vision fallback — already over the latency budget.")

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
    vlm: VlmClient | None = None,
    timeout_ms: float | None = 5000.0,
):
    """Yield (application_key, VerificationResult | Exception) as each completes.

    Per-item failures are isolated (design 3.7) — a corrupt image surfaces as that
    item's own error, everything else finishes.
    """
    for app in apps:
        try:
            yield app.key, verify(app, ocr, vlm=vlm, timeout_ms=timeout_ms)
        except Exception as exc:  # noqa: BLE001 - isolation is the point
            yield app.key, exc


def _load_images(app: LabelApplication) -> dict[int, Image.Image]:
    out: dict[int, Image.Image] = {}
    for i, ref in enumerate(app.images):
        try:
            out[i] = Image.open(ref.path)
        except OSError:
            continue
    return out


def _apply_vlm_fallback(
    app: LabelApplication,
    checks: list[CheckResult],
    vlm: VlmClient,
    notes: list[str],
) -> list[CheckResult]:
    """Retry OCR-unreadable text fields with the vision model (design 2.4).

    A value the VLM supplies is still run through the same comparison ladder — the
    fallback changes *how the text was read*, not the rule that judges it. Never
    upgrades straight to PASS without that comparison.
    """
    wanted = {
        c.check_id: getattr(app, _VLM_RETRYABLE[c.check_id])
        for c in checks
        if c.outcome is Outcome.UNREADABLE and c.check_id in _VLM_RETRYABLE
    }
    if not wanted:
        return checks

    readings: dict[str, str] = {}
    for i, ref in enumerate(app.images):
        try:
            fields = vlm.read_fields(ref.path, list(wanted))
        except Exception as exc:  # firewalled / unreachable -> not an error (6.4)
            notes.append(f"Vision fallback unavailable: {exc}")
            return checks
        for cid, field in fields.items():
            readings.setdefault(cid, field.value)

    if not readings:
        return checks
    notes.append(f"Vision fallback read {len(readings)} field(s) OCR could not.")

    out: list[CheckResult] = []
    for c in checks:
        if c.check_id in readings and readings[c.check_id]:
            declared = wanted[c.check_id]
            m = compare(declared, readings[c.check_id])
            out.append(CheckResult(
                c.check_id, c.field_label, m.outcome,
                declared=declared, observed=readings[c.check_id], tier=m.tier,
                detail=f"{m.detail} (read by vision fallback)",
                evidence={"similarity": round(m.similarity, 3), "source": "vlm"},
            ))
        else:
            out.append(c)
    return out
