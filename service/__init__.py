"""FastAPI service for the label verification prototype (Phase 1).

Single-label interactive path: POST /api/verify -> review -> finalize.
Batch: POST /api/verify/batch + SSE.

No persistence (N-05): uploaded images and results live in an in-memory session
store that is swept on a TTL. Restarting the process forgets everything.

**Deliberately free of imports.** `service/app.py` builds the application at
module level (`app = create_app()`), and `python -m service` imports this package
*before* it runs `__main__.py` — so re-exporting `create_app` here meant the app
was constructed, and its AI client chosen, before `__main__.py` had a chance to
read `.env`. The key was sitting in the file and the service still reported no
model configured.

Import from `service.app` directly; nothing was using the shortcut.
"""
