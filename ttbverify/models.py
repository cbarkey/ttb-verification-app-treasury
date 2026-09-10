"""Canonical data types.

Every ingestion path (UI form, JSON, CSV manifest) is an adapter that produces a
`LabelApplication`. The rules engine only ever sees this shape, which keeps it
pure and testable (design 2.2).

Design references:
  - Outcome states: design 2.3
  - Canonical schema: design 2.2
  - "Every finding is explainable" (F-09): CheckResult carries the observed text
    and the box it came from.
"""

from __future__ import annotations

import enum
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any


class Outcome(str, enum.Enum):
    """Per-check outcome (design 2.3).

    `UNREADABLE` is never collapsed into `FAIL` (F-07). `NOT_DECLARED` means there
    was no application value to compare against (design 2.2, 3.6) — also never a
    failure.
    """

    PASS = "PASS"
    REVIEW = "REVIEW"
    FAIL = "FAIL"
    UNREADABLE = "UNREADABLE"
    NOT_DECLARED = "NOT_DECLARED"

    def __str__(self) -> str:  # nicer report output
        return self.value


# Plain-language labels for the default (non-technical) UI view (N-04, design 2.3).
OUTCOME_LABEL = {
    Outcome.PASS: "Matches",
    Outcome.REVIEW: "Needs your review",
    Outcome.FAIL: "Does not match",
    Outcome.UNREADABLE: "Can't read — request better image",
    Outcome.NOT_DECLARED: "Not declared",
}


class Commodity(str, enum.Enum):
    """Beverage class. Determines which requirements apply to a label."""

    WINE = "wine"
    MALT = "malt"
    SPIRITS = "spirits"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class BoundingBox:
    """Pixel rectangle in a specific image. Origin is top-left (PIL convention)."""

    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def area(self) -> int:
        return max(0, self.width) * max(0, self.height)

    @staticmethod
    def enclosing(boxes: Iterable[BoundingBox]) -> BoundingBox | None:
        boxes = [b for b in boxes if b is not None]
        if not boxes:
            return None
        left = min(b.left for b in boxes)
        top = min(b.top for b in boxes)
        right = max(b.right for b in boxes)
        bottom = max(b.bottom for b in boxes)
        return BoundingBox(left, top, right - left, bottom - top)

    def to_dict(self) -> dict[str, int]:
        return {
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
        }


@dataclass
class ImageRef:
    """One label image. `role` is front / back / neck / None (F-08)."""

    path: str
    role: str | None = None

    @classmethod
    def coerce(cls, value: Any) -> ImageRef:
        if isinstance(value, ImageRef):
            return value
        if isinstance(value, str):
            return cls(path=value)
        if isinstance(value, dict):
            return cls(path=value["path"], role=value.get("role"))
        raise TypeError(f"cannot interpret {value!r} as an ImageRef")

    def __post_init__(self) -> None:
        self.path = os.fspath(self.path)


@dataclass
class LabelApplication:
    """Declared application values + the label image(s) to check them against.

    Declared fields are optional by design (design 2.2): a missing value produces
    `NOT_DECLARED`, never a failure. Only `serial_number`, `brand_name`,
    `class_type`, `commodity` and at least one image are structurally required.
    """

    serial_number: str
    brand_name: str
    class_type: str
    commodity: Commodity
    images: list[ImageRef]

    ttb_id: str | None = None
    permit_number: str | None = None
    fanciful_name: str | None = None
    alcohol_content: str | None = None
    net_contents: str | None = None
    applicant_name: str | None = None
    applicant_address: str | None = None
    origin: str | None = None

    def __post_init__(self) -> None:
        self.commodity = Commodity(self.commodity)
        self.images = [ImageRef.coerce(i) for i in self.images]
        if not self.images:
            raise ValueError("a LabelApplication needs at least one image")

    @property
    def key(self) -> str:
        """14-digit TTB ID when present, else the serial-number fallback."""
        return self.ttb_id or self.serial_number


@dataclass
class CheckResult:
    """One field's verdict, with the evidence that produced it (F-09).

    `observed` is the text read off the label (original casing preserved).
    `box` is where on `image_index` that text sits, for the review overlay.
    `tier` records which normalization tier fired, so the UI can say
    "matched after ignoring capitalization" rather than just "pass".
    `evidence` carries check-specific structured data (e.g. the W-2 word diff,
    the W-4 density measurement).
    """

    check_id: str
    field_label: str
    outcome: Outcome
    declared: str | None = None
    observed: str | None = None
    detail: str = ""
    tier: str | None = None
    box: BoundingBox | None = None
    image_index: int | None = None
    image_role: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def needs_agent(self) -> bool:
        """True when this check is not clean — the agent's exception queue."""
        return self.outcome in (Outcome.REVIEW, Outcome.FAIL, Outcome.UNREADABLE)

    @property
    def agent_resolvable(self) -> bool:
        """True when an agent can flip this to a decision (design 2.5.3).

        FAIL items are shown with evidence but are not agent-resolvable.
        """
        return self.outcome is Outcome.REVIEW

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "field_label": self.field_label,
            "outcome": self.outcome.value,
            "outcome_label": OUTCOME_LABEL[self.outcome],
            "declared": self.declared,
            "observed": self.observed,
            "detail": self.detail,
            "tier": self.tier,
            "box": self.box.to_dict() if self.box else None,
            "image_index": self.image_index,
            "image_role": self.image_role,
            "evidence": self.evidence,
        }


# Verdict precedence: the worst outcome present wins, with NOT_DECLARED and a
# clean PASS both counting as "nothing wrong".
_VERDICT_ORDER = [
    Outcome.FAIL,
    Outcome.UNREADABLE,
    Outcome.REVIEW,
    Outcome.PASS,
    Outcome.NOT_DECLARED,
]


@dataclass
class VerificationResult:
    """Everything one label check produced: verdicts, evidence, and timings.

    `verdict` is the worst outcome present, not an average — one FAIL makes
    the label a FAIL. `notes` carries anything the agent should know that
    isn't a per-field finding: a straightened image, an unreadable upload, a
    model consulted, a budget overrun.
    """

    application_key: str
    checks: list[CheckResult]
    elapsed_ms: int = 0
    stage_ms: dict[str, float] = field(default_factory=dict)
    ocr_available: bool = True
    notes: list[str] = field(default_factory=list)

    @property
    def verdict(self) -> Outcome:
        present = {c.outcome for c in self.checks}
        for outcome in _VERDICT_ORDER:
            if outcome in present:
                return outcome
        return Outcome.NOT_DECLARED

    @property
    def review_items(self) -> list[CheckResult]:
        return [c for c in self.checks if c.outcome is Outcome.REVIEW]

    @property
    def summary_line(self) -> str:
        """The plain-language lead on the result screen (design 2.5.1)."""
        total = len(self.checks)
        verdict = self.verdict
        if verdict is Outcome.PASS or verdict is Outcome.NOT_DECLARED:
            passed = sum(
                1 for c in self.checks
                if c.outcome in (Outcome.PASS, Outcome.NOT_DECLARED)
            )
            return f"Looks good — {passed} of {total} checks passed."
        if verdict is Outcome.UNREADABLE:
            return "Couldn't read this label."
        needing = sum(1 for c in self.checks if c.needs_agent)
        noun = "item" if needing == 1 else "items"
        verb = "need attention" if verdict is Outcome.FAIL else "need your review"
        if needing == 1:
            verb = verb.replace("need", "needs")
        return f"{needing} {noun} {verb}."

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_key": self.application_key,
            "verdict": self.verdict.value,
            "summary_line": self.summary_line,
            "elapsed_ms": self.elapsed_ms,
            "stage_ms": self.stage_ms,
            "ocr_available": self.ocr_available,
            "notes": self.notes,
            "checks": [c.to_dict() for c in self.checks],
        }
