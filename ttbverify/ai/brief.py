"""Use B: the batch triage brief (DESIGN.md 2.9).

Sarah Chen's problem is 200-300 applications arriving at once and 47 agents to
work them. The queue table already tells her *what* failed; what it doesn't tell
her is that thirty of the forty exceptions are one importer making one mistake.
A `groupby` gets some of that. The cross-cutting version — "these six are the
same rounding error, that one is unrelated and needs a fresh photo" — is the part
it doesn't.

Three properties keep this out of the regulatory path entirely:

  * **It runs once, after the batch has finished.** N-01 is untouched; the cost
    is one call per batch regardless of size.
  * **It is sent structured findings, never images.** Serials, verdicts,
    per-check outcomes, declared vs observed. Less data leaves the process, and
    the model cannot re-read a label and disagree with the engine about it.
  * **It is prose above the table; the table stays the record.** If the call
    fails the brief is simply absent — no row changes, nothing is retried, and
    the CSV export is byte-identical either way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ttbverify.ai.client import AiClient, AiRequest, prompt

# Enough exceptions to spot a pattern, few enough to keep one call cheap and
# inside a sane token budget on a 300-item batch.
MAX_ITEMS = 60

_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "maxLength": 300},
        "groups": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "maxLength": 120},
                    "count": {"type": "number"},
                    "detail": {"type": "string", "maxLength": 400},
                },
                "required": ["label", "detail"],
            },
        },
        "watch_outs": {
            "type": "array",
            "maxItems": 3,
            "items": {"type": "string", "maxLength": 300},
        },
    },
    "required": ["headline"],
}


@dataclass(frozen=True)
class Group:
    """One cluster of exceptions a supervisor can work as a single job."""

    label: str
    count: int
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "count": self.count, "detail": self.detail}


@dataclass(frozen=True)
class Brief:
    """Advisory only. `generated` is what the UI labels it with."""

    headline: str
    groups: list[Group] = field(default_factory=list)
    watch_outs: list[str] = field(default_factory=list)
    model: str = ""
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "headline": self.headline,
            "groups": [g.to_dict() for g in self.groups],
            "watch_outs": list(self.watch_outs),
            "model": self.model,
            "truncated": self.truncated,
            "generated": True,
            "advisory": True,
        }


def findings_for(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    """Reduce batch rows to the exceptions, in the shape the prompt expects.

    Clean rows are dropped: they are not the supervisor's queue, and sending 260
    passes to describe 40 problems wastes the budget on the part that needs no
    triage.
    """
    exceptions = []
    for row in rows:
        if row.get("verdict") in (None, "PASS", "NOT_DECLARED"):
            continue
        flagged = [
            {
                "check": c.get("check_id"),
                "outcome": c.get("outcome"),
                "declared": c.get("declared"),
                "observed": c.get("observed"),
                "detail": (c.get("detail") or "")[:160],
            }
            for c in row.get("checks", [])
            if c.get("outcome") in ("FAIL", "REVIEW", "UNREADABLE")
        ]
        exceptions.append({
            "serial": row.get("serial_number") or row.get("application_key"),
            "brand": row.get("brand_name"),
            "verdict": row.get("verdict"),
            "flagged": flagged,
        })
    truncated = len(exceptions) > MAX_ITEMS
    return exceptions[:MAX_ITEMS], truncated


def summarize(client: AiClient, rows: list[dict[str, Any]]
              ) -> tuple[Brief | None, str | None]:
    """Returns (brief, error). Never raises; a failure means no brief."""
    import json

    if not client.available:
        return None, None
    exceptions, truncated = findings_for(rows)
    if not exceptions:
        return None, None

    result = client.complete(AiRequest(
        kind="batch_brief",
        prompt=prompt("batch_brief",
                      findings=json.dumps(exceptions, indent=1, sort_keys=True)),
        schema=_SCHEMA,
        tool_name="report_triage_brief",
        max_tokens=1500,
    ))
    if not result.ok:
        return None, result.error

    groups = [
        Group(label=g.get("label", ""), count=int(g.get("count", 0) or 0),
              detail=g.get("detail", ""))
        for g in result.data.get("groups", [])
    ]
    return Brief(
        headline=result.data.get("headline", ""),
        groups=groups,
        watch_outs=list(result.data.get("watch_outs", [])),
        model=result.model,
        truncated=truncated,
    ), None
