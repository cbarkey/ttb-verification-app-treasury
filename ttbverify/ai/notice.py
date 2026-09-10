"""Use C: draft the rejection notice (CLAUDE.md 2.9).

Agents write these by hand today, from findings a machine already produced. This
turns the findings into a first draft. It decides nothing — by the time this is
called the verdict exists, the agent has read it, and they have clicked a button
asking for wording.

Three deliberate limits:

  * **Behind a button.** No call happens unless an agent asks, so an unused
    feature costs nothing per label.
  * **Findings in, prose out.** The word-level warning diff, the declared value,
    the observed value — all already computed. The model is not re-reading the
    label and cannot introduce a fact the engine didn't establish.
  * **The agent owns the text.** It lands in a copy box to edit and send, not in
    an outbox. `items` comes back separately so lines can be dropped without
    rewriting the body.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ttbverify.ai.client import AiClient, AiRequest, prompt

_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string", "maxLength": 200},
        "body": {"type": "string", "maxLength": 4000},
        "items": {
            "type": "array",
            "maxItems": 12,
            "items": {"type": "string", "maxLength": 300},
        },
    },
    "required": ["subject", "body"],
}


@dataclass(frozen=True)
class Notice:
    subject: str
    body: str
    items: list[str] = field(default_factory=list)
    model: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "body": self.body,
            "items": list(self.items),
            "model": self.model,
            "generated": True,
            "advisory": True,
        }


def findings_for(result_dict: dict[str, Any]) -> list[dict[str, Any]]:
    """The flagged checks, trimmed to what a notice needs to be specific."""
    out = []
    for check in result_dict.get("checks", []):
        if check.get("outcome") not in ("FAIL", "REVIEW", "UNREADABLE"):
            continue
        item = {
            "check": check.get("check_id"),
            "field": check.get("field_label"),
            "outcome": check.get("outcome"),
            "declared": check.get("declared"),
            "observed": check.get("observed"),
            "detail": check.get("detail"),
        }
        # The W-2 word diff is the whole reason a warning rejection is
        # defensible; it is the one piece of evidence worth passing through.
        diff = (check.get("evidence") or {}).get("diff")
        if diff:
            item["wording_differences"] = diff[:20]
        out.append(item)
    return out


def draft(client: AiClient, application: dict[str, Any],
          result_dict: dict[str, Any]) -> tuple[Notice | None, str | None]:
    """Returns (notice, error). Never raises."""
    import json

    if not client.available:
        return None, "no model configured"
    findings = findings_for(result_dict)
    if not findings:
        return None, "nothing to write about — no flagged findings"

    result = client.complete(AiRequest(
        kind="rejection_notice",
        prompt=prompt(
            "rejection_notice",
            application=json.dumps(application, sort_keys=True),
            findings=json.dumps(findings, indent=1, sort_keys=True),
        ),
        schema=_SCHEMA,
        tool_name="report_notice",
        max_tokens=2000,
    ))
    if not result.ok:
        return None, result.error
    return Notice(
        subject=result.data.get("subject", ""),
        body=result.data.get("body", ""),
        items=list(result.data.get("items", [])),
        model=result.model,
    ), None
