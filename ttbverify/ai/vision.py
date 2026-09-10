"""Use A: read fields OCR could not (CLAUDE.md 2.9).

This is the only model call on the per-label path, and it is conditional — it
fires only when a field is still `UNREADABLE` after deskew and OCR. On a clean
label it never runs at all, which is what keeps N-01 intact.

**One call per image, not one per field.** The model is looking at the whole
label either way; asking six times costs six round trips inside a 5 s budget for
no more information.

The cap that makes this safe lives in `pipeline._apply_vision_fallback`, not
here: whatever comes back can only ever produce `REVIEW`. This module's contract
is narrower than that and worth stating plainly — it returns *readings*, and a
reading is a claim about what is printed, which is exactly the kind of claim a
human can check in one glance against the crop next to it.
"""

from __future__ import annotations

from dataclasses import dataclass

from ttbverify.ai.client import (
    VISION_TIMEOUT_S,
    AiClient,
    AiRequest,
    prompt,
)

# check_id -> what to tell the model that field means. Only the fields actually
# being asked for are described in the prompt: a label whose brand read fine
# doesn't need the model reminded what a brand is, and a shorter prompt is a
# cheaper and less distractible one.
FIELD_NAMES = {
    "brand": "the brand name in display type — the label's own name for the "
             "product. Not the producer's corporate name in the small print at "
             "the bottom, unless the same words also appear as the display brand",
    "class_type": "the class or type designation, e.g. \"Kentucky Straight "
                  "Bourbon Whiskey\", \"London Dry Gin\", \"Bordeaux Superieur\"",
    "producer": "the bottler or producer name from the \"Bottled by\" / "
                "\"Produced by\" / \"Distilled by\" statement",
    "origin": "the country-of-origin statement, e.g. \"Product of France\"",
    "abv": "the alcohol content exactly as printed, e.g. \"45% Alc./Vol. (90 Proof)\"",
    "net_contents": "the net contents exactly as printed, e.g. \"750 mL\"",
}

_SCHEMA = {
    "type": "object",
    "properties": {
        "fields": {
            "type": "array",
            "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "enum": sorted(FIELD_NAMES)},
                    "text": {"type": "string", "maxLength": 300},
                    "confidence": {"type": "number"},
                },
                "required": ["name"],
            },
        },
    },
    "required": ["fields"],
}


@dataclass(frozen=True)
class Reading:
    """One field the model claims to have read off one image."""

    check_id: str
    text: str
    confidence: float
    image_index: int
    model: str


def build_request(image_path: str, check_ids: list[str]) -> AiRequest:
    """The request for one image.

    Shared with `scripts/record_cassettes.py`, so a recording is keyed by exactly
    what the pipeline will later ask for — a recorder that built its own request
    would produce cassettes that never match.
    """
    return AiRequest(
        kind="vision_fields",
        prompt=prompt("vision_fields",
                      fields="\n".join(f"- {c}: {FIELD_NAMES[c]}" for c in check_ids)),
        schema=_SCHEMA,
        tool_name="report_label_fields",
        images=(image_path,),
        max_tokens=1024,
        timeout_s=VISION_TIMEOUT_S,
    )


def read_fields(client: AiClient, image_path: str, check_ids: list[str], *,
                image_index: int = 0) -> tuple[list[Reading], str | None]:
    """Ask for `check_ids` from one image. Returns (readings, error).

    Never raises. An unreachable model, a timeout, a malformed reply and an
    absent key all come back the same way: no readings, plus a reason the caller
    can put in `notes`.
    """
    wanted = [c for c in check_ids if c in FIELD_NAMES]
    if not wanted or not client.available:
        return [], None

    result = client.complete(build_request(image_path, wanted))
    if not result.ok:
        return [], result.error

    readings: list[Reading] = []
    for item in result.data.get("fields", []):
        name = item.get("name")
        text = (item.get("text") or "").strip()
        # A null/blank reading is the model saying "not on this image", which is
        # a real answer and must not be turned into a value.
        if name not in wanted or not text:
            continue
        readings.append(Reading(
            check_id=name,
            text=text,
            confidence=float(item.get("confidence", 0.0) or 0.0),
            image_index=image_index,
            model=result.model,
        ))
    return readings, None
