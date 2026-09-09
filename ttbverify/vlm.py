"""Conditional vision-model fallback, behind an interface (design 2.4, N-06).

The pipeline is local-OCR-first. A VLM is consulted only for fields OCR could not
locate or read — never on every label, because one network round trip would eat
the entire single-label latency budget (design 6.1).

`NullVlm` is the default and what every test uses: it reports `available = False`
and returns nothing, so the system runs fully with no outbound network. This
doubles as the proof of the no-egress path (N-06). `ClaudeVlm` is only
constructed when `ANTHROPIC_API_KEY` is present; if the key is absent or the
`anthropic` package isn't installed, `make_default_vlm()` falls back to `NullVlm`.

`VLM unreachable / firewalled` is not an error condition here — affected fields
stay REVIEW / UNREADABLE with the reason "automated check unavailable", never
PASS (design 6.4).
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
from dataclasses import dataclass
from typing import Protocol

from ttbverify.models import BoundingBox

_DEFAULT_MODEL = "claude-sonnet-5"


@dataclass
class VlmField:
    name: str
    value: str | None
    confidence: float = 0.0
    box: BoundingBox | None = None


class VlmClient(Protocol):
    @property
    def available(self) -> bool: ...

    @property
    def name(self) -> str: ...

    def read_fields(self, image_path: str, fields: list[str]) -> dict[str, VlmField]: ...


class NullVlm:
    """No-op fallback. The default everywhere; the only VLM the tests see."""

    available = False
    name = "null"

    def read_fields(self, image_path: str, fields: list[str]) -> dict[str, VlmField]:
        return {}


_PROMPT = (
    "You are helping verify a US TTB alcohol beverage label. Read the attached "
    "label image and report ONLY what is printed on it for these fields: {fields}. "
    "Respond with a compact JSON object mapping each field name to either the "
    "exact text as printed (preserving capitalization) or null if it does not "
    "appear. Add a sibling object \"confidence\" mapping each field to a number "
    "from 0 to 1. No prose, no code fence."
)


class ClaudeVlm:
    """Anthropic vision implementation. Constructed only when a key is available."""

    name = "claude"

    def __init__(self, api_key: str | None = None, model: str = _DEFAULT_MODEL):
        self.model = model
        self._client = None
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return
        try:
            import anthropic

            self._client = anthropic.Anthropic(api_key=key)
        except ImportError:
            self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    def read_fields(self, image_path: str, fields: list[str]) -> dict[str, VlmField]:
        if not self._client:
            return {}
        media_type = mimetypes.guess_type(image_path)[0] or "image/png"
        with open(image_path, "rb") as fh:
            data = base64.standard_b64encode(fh.read()).decode("ascii")

        msg = self._client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": media_type, "data": data}},
                    {"type": "text", "text": _PROMPT.format(fields=", ".join(fields))},
                ],
            }],
        )
        text = "".join(
            block.text for block in msg.content if getattr(block, "type", None) == "text"
        )
        return _parse_response(text, fields)


def _parse_response(text: str, fields: list[str]) -> dict[str, VlmField]:
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return {}
    values = payload if isinstance(payload, dict) else {}
    conf = values.get("confidence", {}) if isinstance(values.get("confidence"), dict) else {}
    out: dict[str, VlmField] = {}
    for name in fields:
        raw = values.get(name)
        if raw is None:
            continue
        try:
            c = float(conf.get(name, 0.0))
        except (TypeError, ValueError):
            c = 0.0
        out[name] = VlmField(name=name, value=str(raw), confidence=c)
    return out


def make_default_vlm() -> VlmClient:
    """`ClaudeVlm` when a key is present and usable, otherwise `NullVlm`."""
    claude = ClaudeVlm()
    return claude if claude.available else NullVlm()
