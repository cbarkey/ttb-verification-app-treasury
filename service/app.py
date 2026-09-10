"""FastAPI application: single-label verify -> review -> finalize."""

from __future__ import annotations

import io
import json
import os
import tempfile

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import ValidationError

from service.schemas import (
    DecisionRequest,
    DecisionResponse,
    DeclaredFields,
    FinalizeRequest,
    FinalizeResponse,
    HealthResponse,
    ImageMeta,
    NoticeResponse,
    SessionResponse,
    VerifyResponse,
)
from service.sessions import SessionStore, StoredImage
from ttbverify.ai import make_default_client
from ttbverify.models import LabelApplication, Outcome
from ttbverify.ocr import NullOcr, TesseractOcr
from ttbverify.pipeline import verify

MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_IMAGES = 6
_ALLOWED_TYPES = {"image/png", "image/jpeg", "image/webp", "image/tiff"}
_ROLE_BY_INDEX = ["front", "back", "neck"]

_WEB_DIST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "web", "dist")


def create_app(*, ocr=None, ai=None) -> FastAPI:
    """Build the app.

    `ocr` and `ai` are injectable so a test — or a demo run replaying recorded
    cassettes — can exercise a path a given machine cannot reach live. Both
    default to "whatever this environment actually has", which behind a firewall
    is Tesseract plus no model at all (N-06).
    """
    app = FastAPI(
        title="TTB Label Verification (prototype)",
        version="0.1.0",
        summary="Standalone proof-of-concept — no COLA integration, no persistence.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # standalone POC, no auth, no sensitive data (brief)
        allow_methods=["*"],
        allow_headers=["*"],
    )

    store = SessionStore()
    if ocr is None:
        ocr = TesseractOcr() if TesseractOcr.is_available() else NullOcr()
    if ai is None:
        ai = make_default_client()
    app.state.store = store
    app.state.ocr = ocr
    app.state.ai = ai

    from service.routes_batch import make_batch_router

    batch_router = make_batch_router(ocr=ocr, ai=ai)
    app.include_router(batch_router)
    app.state.batch_store = batch_router.batch_store

    # ---- helpers --------------------------------------------------------

    def _image_meta(sid: str, images: list[StoredImage]) -> list[ImageMeta]:
        return [
            ImageMeta(index=im.index, role=im.role, width=im.width, height=im.height,
                      url=f"/api/sessions/{sid}/images/{im.index}")
            for im in images
        ]

    def _review_state(session) -> tuple[list[str], bool]:
        review_ids = [c.check_id for c in session.result.checks
                      if c.outcome is Outcome.REVIEW]
        unresolved = [cid for cid in review_ids if cid not in session.decisions]
        return unresolved, not unresolved

    # ---- routes --------------------------------------------------------

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            ocr="available" if isinstance(ocr, TesseractOcr) else "degraded",
            ocr_engine=type(ocr).__name__,
            active_sessions=len(store),
            ai="available" if ai.available else "unavailable",
            ai_model=ai.model or None,
            ai_unavailable_reason=getattr(ai, "unavailable_reason", None)
            if not ai.available else None,
        )

    @app.post("/api/verify", response_model=VerifyResponse)
    async def verify_label(
        application: str = Form(..., description="JSON object of declared fields"),
        images: list[UploadFile] = File(...),
        roles: list[str] | None = Form(None),
    ) -> VerifyResponse:
        try:
            payload = json.loads(application)
        except json.JSONDecodeError as exc:
            raise HTTPException(422, f"application field is not valid JSON: {exc}") from exc
        try:
            fields = DeclaredFields.model_validate(payload)
        except ValidationError as exc:
            raise HTTPException(422, exc.errors()) from exc

        if not images:
            raise HTTPException(422, "at least one image is required")
        if len(images) > MAX_IMAGES:
            raise HTTPException(422, f"at most {MAX_IMAGES} images")

        stored: list[StoredImage] = []
        for i, upload in enumerate(images):
            data = await upload.read()
            if len(data) > MAX_IMAGE_BYTES:
                raise HTTPException(413, f"image '{upload.filename}' exceeds "
                                         f"{MAX_IMAGE_BYTES // (1024 * 1024)} MB")
            ctype = upload.content_type or "image/png"
            if ctype not in _ALLOWED_TYPES:
                raise HTTPException(415, f"unsupported image type '{ctype}' for "
                                         f"'{upload.filename}'")
            try:
                with Image.open(io.BytesIO(data)) as im:
                    im.verify()
                with Image.open(io.BytesIO(data)) as im:
                    w, h = im.size
            except Exception as exc:  # any decode failure gives the same answer
                raise HTTPException(
                    422, f"'{upload.filename}' is not a readable image") from exc
            role = None
            if roles and i < len(roles) and roles[i]:
                role = roles[i]
            elif i < len(_ROLE_BY_INDEX):
                role = _ROLE_BY_INDEX[i]
            stored.append(StoredImage(index=i, role=role, content_type=ctype,
                                      data=data, width=w, height=h))

        with tempfile.TemporaryDirectory(prefix="ttbverify_") as tmp:
            image_refs = []
            for im in stored:
                ext = {"image/png": ".png", "image/jpeg": ".jpg",
                       "image/webp": ".webp", "image/tiff": ".tif"}.get(
                    im.content_type, ".png")
                path = os.path.join(tmp, f"img_{im.index}{ext}")
                with open(path, "wb") as fh:
                    fh.write(im.data)
                image_refs.append({"path": path, "role": im.role})
            app_model = LabelApplication(
                images=image_refs,
                **fields.model_dump(exclude_none=False),
            )
            result = verify(app_model, ocr, ai=ai)

        session = store.create(app_model, stored, result)
        return VerifyResponse(
            session_id=session.id,
            result=result.to_dict(),
            images=_image_meta(session.id, stored),
        )

    @app.get("/api/sessions/{sid}", response_model=SessionResponse)
    def get_session(sid: str) -> SessionResponse:
        session = store.get(sid)
        if session is None:
            raise HTTPException(404, "session not found or expired")
        unresolved, can_finalize = _review_state(session)
        return SessionResponse(
            session_id=session.id,
            result=session.result.to_dict(),
            images=_image_meta(session.id, session.images),
            decisions=session.decisions,
            unresolved_review_ids=unresolved,
            can_finalize=can_finalize,
            finalized=session.finalized,
        )

    @app.get("/api/sessions/{sid}/images/{index}")
    def get_image(sid: str, index: int) -> Response:
        session = store.get(sid)
        if session is None:
            raise HTTPException(404, "session not found or expired")
        for im in session.images:
            if im.index == index:
                return Response(content=im.data, media_type=im.content_type,
                                headers={"Cache-Control": "private, max-age=3600"})
        raise HTTPException(404, "image not found")

    @app.post("/api/sessions/{sid}/decisions", response_model=DecisionResponse)
    def record_decision(sid: str, body: DecisionRequest) -> DecisionResponse:
        session = store.get(sid)
        if session is None:
            raise HTTPException(404, "session not found or expired")
        check = next((c for c in session.result.checks
                      if c.check_id == body.check_id), None)
        if check is None:
            raise HTTPException(404, f"no check '{body.check_id}' in this session")
        if check.outcome is not Outcome.REVIEW:
            raise HTTPException(409, f"check '{body.check_id}' is {check.outcome.value}, "
                                     "not an agent-resolvable review item")
        session.decisions[body.check_id] = body.decision
        unresolved, can_finalize = _review_state(session)
        return DecisionResponse(decisions=session.decisions,
                                unresolved_review_ids=unresolved,
                                can_finalize=can_finalize)

    @app.post("/api/sessions/{sid}/draft-notice", response_model=NoticeResponse)
    def draft_notice(sid: str) -> NoticeResponse:
        """2.9 use C — draft the rejection notice for this label.

        The decision is already made by the time an agent clicks this; the model
        is turning findings the rules engine produced into wording, and the agent
        edits and owns the result.
        """
        from ttbverify.ai import notice as drafting

        session = store.get(sid)
        if session is None:
            raise HTTPException(404, "session not found or expired")
        application = {
            k: v for k, v in vars(session.application).items() if k != "images"
        }
        draft, error = drafting.draft(ai, _jsonable(application),
                                      session.result.to_dict())
        if draft is None:
            raise HTTPException(503, error or "no draft available")
        return NoticeResponse(**draft.to_dict())

    @app.post("/api/sessions/{sid}/finalize", response_model=FinalizeResponse)
    def finalize(sid: str, body: FinalizeRequest) -> FinalizeResponse:
        session = store.get(sid)
        if session is None:
            raise HTTPException(404, "session not found or expired")
        session.finalized = body.action
        return FinalizeResponse(session_id=session.id, action=body.action,
                                decisions=session.decisions)

    def _jsonable(values: dict) -> dict:
        return {k: (str(v) if v is not None else None) for k, v in values.items()}

    # ---- static frontend (built React app), if present ----------------

    if os.path.isdir(_WEB_DIST):
        app.mount("/assets", StaticFiles(directory=os.path.join(_WEB_DIST, "assets")),
                  name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str, request: Request):
            if full_path.startswith("api/"):
                raise HTTPException(404)
            candidate = os.path.join(_WEB_DIST, full_path)
            if full_path and os.path.isfile(candidate):
                return FileResponse(candidate)
            return FileResponse(os.path.join(_WEB_DIST, "index.html"))

    return app


app = create_app()
