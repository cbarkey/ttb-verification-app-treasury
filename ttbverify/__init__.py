"""TTB alcohol label verification core (Phase 0).

Public surface is intentionally small: build a `LabelApplication`, pass it to
`ttbverify.pipeline.verify` with an OCR engine, get a `VerificationResult`.
"""

from ttbverify.models import (
    BoundingBox,
    CheckResult,
    Commodity,
    ImageRef,
    LabelApplication,
    Outcome,
    VerificationResult,
)

__all__ = [
    "BoundingBox",
    "CheckResult",
    "Commodity",
    "ImageRef",
    "LabelApplication",
    "Outcome",
    "VerificationResult",
]
