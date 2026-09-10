"""In-memory session store (N-05 — nothing persisted beyond the session).

A session holds one application's uploaded image bytes, its VerificationResult,
and the agent's review decisions. Entries expire on a TTL so a long-running
process doesn't accumulate label images indefinitely.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from threading import Lock

from ttbverify.models import LabelApplication, VerificationResult

SESSION_TTL_SECONDS = 60 * 60  # 1 hour
MAX_SESSIONS = 200


@dataclass
class StoredImage:
    """One uploaded image, held in memory for the life of the session (N-05)."""

    index: int
    role: str | None
    content_type: str
    data: bytes
    width: int
    height: int


@dataclass
class Session:
    """One single-label review: the result, plus the agent's decisions so far."""

    id: str
    application: LabelApplication
    images: list[StoredImage]
    result: VerificationResult
    created_at: float = field(default_factory=time.time)
    # check_id -> "accept" | "reject"
    decisions: dict[str, str] = field(default_factory=dict)
    finalized: str | None = None  # "approve" | "reject" | "request_image"

    def touch(self) -> None:
        self.created_at = time.time()


class SessionStore:
    """In-memory, TTL-swept session store. Restarting forgets everything (N-05)."""

    def __init__(self, ttl: float = SESSION_TTL_SECONDS, max_size: int = MAX_SESSIONS):
        self._ttl = ttl
        self._max = max_size
        self._data: dict[str, Session] = {}
        self._lock = Lock()

    def _sweep(self) -> None:
        now = time.time()
        stale = [k for k, s in self._data.items() if now - s.created_at > self._ttl]
        for k in stale:
            del self._data[k]
        if len(self._data) > self._max:
            for k in sorted(self._data, key=lambda k: self._data[k].created_at)[
                : len(self._data) - self._max
            ]:
                del self._data[k]

    def create(
        self,
        application: LabelApplication,
        images: list[StoredImage],
        result: VerificationResult,
    ) -> Session:
        with self._lock:
            self._sweep()
            sid = secrets.token_urlsafe(9)
            session = Session(id=sid, application=application, images=images, result=result)
            self._data[sid] = session
            return session

    def get(self, sid: str) -> Session | None:
        with self._lock:
            session = self._data.get(sid)
            if session is None:
                return None
            if time.time() - session.created_at > self._ttl:
                del self._data[sid]
                return None
            return session

    def __len__(self) -> int:
        return len(self._data)
