"""FastAPI service for the label verification prototype (Phase 1).

Single-label interactive path today: POST /api/verify -> review -> finalize.
Batch (POST /api/verify/batch + SSE) is a later slice.

No persistence (N-05): uploaded images and results live in an in-memory session
store that is swept on a TTL. Restarting the process forgets everything.
"""

from service.app import create_app

__all__ = ["create_app"]
