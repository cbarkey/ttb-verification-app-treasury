"""In-memory batch store (N-05).

A batch holds every manifest row's images + result + the agent's review
decisions, from pre-flight through to a CSV export. Like `SessionStore`, it is
memory-only and TTL-swept; restarting the process forgets everything.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from threading import Lock

from service.manifest import PreflightReport
from service.sessions import StoredImage
from ttbverify.models import LabelApplication, Outcome, VerificationResult

BATCH_TTL_SECONDS = 4 * 60 * 60
MAX_BATCHES = 20
MAX_ROWS = 400
MAX_ZIP_BYTES = 250 * 1024 * 1024


@dataclass
class BatchRow:
    serial_number: str
    line: int
    fields: dict | None                       # canonical-schema values; None if blocked
    images: list[StoredImage]
    blocked_reason: str | None = None
    application: LabelApplication | None = None   # built when processing starts
    status: str = "pending"                   # pending | running | done | error
    result: VerificationResult | None = None
    error: str | None = None
    decisions: dict[str, str] = field(default_factory=dict)
    finalized: str | None = None

    @property
    def processable(self) -> bool:
        return self.fields is not None and self.blocked_reason is None

    @property
    def brand_name(self) -> str:
        return (self.fields or {}).get("brand_name") or "(blocked)"

    @property
    def verdict(self) -> str:
        if self.blocked_reason:
            return "BLOCKED"
        if self.status == "error":
            return "ERROR"
        return self.result.verdict.value if self.result else "PENDING"

    def review_state(self) -> tuple[list[str], bool]:
        if not self.result:
            return [], False
        review_ids = [c.check_id for c in self.result.checks
                      if c.outcome is Outcome.REVIEW]
        unresolved = [c for c in review_ids if c not in self.decisions]
        return unresolved, not unresolved

    def summary(self) -> dict:
        unresolved, can_finalize = self.review_state()
        needs = 0
        if self.result:
            needs = sum(1 for c in self.result.checks if c.needs_agent)
        return {
            "serial_number": self.serial_number,
            "line": self.line,
            "brand_name": self.brand_name,
            "status": self.status,
            "verdict": self.verdict,
            "blocked_reason": self.blocked_reason,
            "error": self.error,
            "needs_attention": needs,
            "elapsed_ms": self.result.elapsed_ms if self.result else None,
            "unresolved_review_ids": unresolved,
            "can_finalize": can_finalize,
            "finalized": self.finalized,
        }


# Exception queue ordering (design 5.4): FAIL first, then REVIEW, then the rest.
_VERDICT_SORT = {"ERROR": 0, "FAIL": 1, "UNREADABLE": 2, "REVIEW": 3,
                 "BLOCKED": 4, "PASS": 5, "NOT_DECLARED": 6, "PENDING": 7}


@dataclass
class Batch:
    id: str
    rows: list[BatchRow]
    preflight: PreflightReport
    created_at: float = field(default_factory=time.time)
    state: str = "ready"                       # ready | running | complete
    started_at: float | None = None
    finished_at: float | None = None
    # Advisory triage brief (2.9 use B). Absent is a normal state — no model
    # configured, the call failed, or there were no exceptions to triage. Nothing
    # else about the batch changes either way.
    brief: dict | None = None
    brief_error: str | None = None

    def row(self, serial: str) -> BatchRow | None:
        return next((r for r in self.rows if r.serial_number == serial), None)

    @property
    def processable(self) -> list[BatchRow]:
        return [r for r in self.rows if r.processable]

    def queue_order(self) -> list[BatchRow]:
        return sorted(
            self.rows,
            key=lambda r: (_VERDICT_SORT.get(r.verdict, 9), r.line),
        )

    def exception_serials(self) -> list[str]:
        return [r.serial_number for r in self.queue_order()
                if r.verdict in ("ERROR", "FAIL", "UNREADABLE", "REVIEW")]

    def progress(self) -> dict:
        done = sum(1 for r in self.processable if r.status in ("done", "error"))
        return {"done": done, "total": len(self.processable), "state": self.state}

    def rows_for_brief(self) -> list[dict]:
        """Structured findings for the triage brief — never the images (2.9)."""
        out = []
        for row in self.queue_order():
            if not row.result:
                continue
            out.append({
                "serial_number": row.serial_number,
                "brand_name": row.brand_name,
                "verdict": row.verdict,
                "checks": [c.to_dict() for c in row.result.checks],
            })
        return out

    def to_dict(self) -> dict:
        return {
            "batch_id": self.id,
            "state": self.state,
            "progress": self.progress(),
            "preflight": self.preflight.to_dict(),
            "rows": [r.summary() for r in self.queue_order()],
            "exception_serials": self.exception_serials(),
            "brief": self.brief,
        }


class BatchStore:
    def __init__(self, ttl: float = BATCH_TTL_SECONDS, max_size: int = MAX_BATCHES):
        self._ttl = ttl
        self._max = max_size
        self._data: dict[str, Batch] = {}
        self._lock = Lock()

    def _sweep(self) -> None:
        now = time.time()
        for k in [k for k, b in self._data.items() if now - b.created_at > self._ttl]:
            del self._data[k]
        if len(self._data) > self._max:
            for k in sorted(self._data, key=lambda k: self._data[k].created_at)[
                : len(self._data) - self._max
            ]:
                del self._data[k]

    def create(self, rows: list[BatchRow], preflight: PreflightReport) -> Batch:
        with self._lock:
            self._sweep()
            bid = secrets.token_urlsafe(9)
            batch = Batch(id=bid, rows=rows, preflight=preflight)
            self._data[bid] = batch
            return batch

    def get(self, bid: str) -> Batch | None:
        with self._lock:
            batch = self._data.get(bid)
            if batch and time.time() - batch.created_at > self._ttl:
                del self._data[bid]
                return None
            return batch

    def __len__(self) -> int:
        return len(self._data)
