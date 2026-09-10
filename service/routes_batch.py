"""Batch endpoints: ZIP upload -> pre-flight -> streamed processing -> per-row review.

Design 2.2 (ZIP packaging), 3.4 (pre-flight), 5.4 (exception queue), 6.3 (isolated
per-item failures), N-02 (throughput + first results stream in early).
"""

from __future__ import annotations

import asyncio
import csv
import io
import os
import tempfile
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from PIL import Image

from service.batch import (
    MAX_ROWS,
    MAX_ZIP_BYTES,
    Batch,
    BatchRow,
    BatchStore,
)
from service.manifest import blank_template, parse_manifest, reconcile
from service.sessions import StoredImage
from ttbverify.ai import brief as triage
from ttbverify.models import LabelApplication, Outcome
from ttbverify.pipeline import verify

_CTYPE = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
          ".webp": "image/webp", ".tif": "image/tiff", ".tiff": "image/tiff"}
_PER_LABEL_TIMEOUT_MS = 5000.0
# Never more than this even on a big host: past a handful of concurrent
# tesseract processes the bottleneck is memory and disk, not cores.
_WORKER_CEILING = 4


def _available_cpus() -> float:
    """How many CPUs this process may actually use.

    **Not `os.cpu_count()`.** In a container that reports the *host's* core
    count, not the quota the container was given — so on a 1-vCPU instance of a
    32-core machine it says 32. This function reads the cgroup quota first and
    only falls back to the host count.
    """
    for path, parse in (
        # cgroup v2: "max 100000" (unlimited) or "50000 100000" (half a core)
        ("/sys/fs/cgroup/cpu.max", lambda t: None if t.split()[0] == "max"
         else float(t.split()[0]) / float(t.split()[1])),
        # cgroup v1: quota and period in separate files
        ("/sys/fs/cgroup/cpu/cpu.cfs_quota_us", lambda t: None if int(t) <= 0
         else int(t) / _read_int("/sys/fs/cgroup/cpu/cpu.cfs_period_us", 100000)),
    ):
        try:
            with open(path) as fh:
                quota = parse(fh.read().strip())
            if quota:
                return quota
        except (OSError, ValueError, ZeroDivisionError, IndexError):
            continue
    return float(os.cpu_count() or 1)


def _read_int(path: str, default: int) -> int:
    try:
        with open(path) as fh:
            return int(fh.read().strip()) or default
    except (OSError, ValueError):
        return default


def batch_workers() -> int:
    """Size the OCR pool to the machine, not to the developer's laptop.

    This was hardcoded to 4, which is a laptop assumption. OCR is CPU-bound and
    each worker shells out to a separate `tesseract` process, so on a 1-vCPU
    instance four workers do not go four times faster — they contend for one
    core and multiply peak memory by four, which on a 2 GB box is a plausible
    way to get OOM-killed mid-batch.

    `TTB_BATCH_WORKERS` overrides it, so a deployment can be tuned without a
    code change.
    """
    override = os.environ.get("TTB_BATCH_WORKERS")
    if override:
        try:
            return max(1, int(override))
        except ValueError:
            pass
    return max(1, min(_WORKER_CEILING, int(_available_cpus())))


def make_batch_router(*, ocr, ai) -> APIRouter:
    """Build the batch routes over one OCR engine and one AI client.

    Takes them as arguments rather than importing globals so a test can hand
    in stubs, and so the app factory decides once what this deployment has.
    """

    router = APIRouter(prefix="/api")
    store = BatchStore()
    router.batch_store = store  # exposed for tests / health

    # Processing runs in a plain daemon thread (not an asyncio task) so it keeps
    # going independently of the request loop; the SSE endpoint just polls the
    # mutating batch state. Per-row work is a bounded thread pool (N-02).

    def _verify_row(row: BatchRow) -> None:
        row.status = "running"
        try:
            row.result = verify(row.application, ocr, ai=ai,
                                timeout_ms=_PER_LABEL_TIMEOUT_MS)
            row.status = "done"
        except Exception as exc:  # noqa: BLE001 - per-item isolation (design 3.7)
            row.status, row.error = "error", str(exc)

    def _process(batch: Batch) -> None:
        batch.state = "running"
        batch.started_at = time.time()
        with ThreadPoolExecutor(max_workers=batch_workers(),
                                thread_name_prefix="verify") as pool:
            futs = [pool.submit(_verify_row, r) for r in batch.processable]
            for _ in as_completed(futs):
                pass
        batch.finished_at = time.time()
        _write_brief(batch)
        # State flips to complete only after the brief has been attempted, so a
        # client that stops listening on "done" never misses it. The brief is
        # advisory and optional; if it fails, this is a no-op (2.9 use B).
        batch.state = "complete"

    def _write_brief(batch: Batch) -> None:
        """One call per batch, after processing, over structured findings only.

        N-01 is untouched — this fires after every row is done. A failure leaves
        `batch.brief` as None and changes nothing else: the rows, the queue order
        and the CSV export are byte-identical with and without it.
        """
        try:
            result, error = triage.summarize(ai, batch.rows_for_brief())
        except Exception as exc:  # noqa: BLE001 — advisory must never break a batch
            batch.brief, batch.brief_error = None, f"{type(exc).__name__}: {exc}"
            return
        batch.brief = result.to_dict() if result else None
        batch.brief_error = error

    # ---- helpers -----------------------------------------------------

    def _get(bid: str) -> Batch:
        batch = store.get(bid)
        if batch is None:
            raise HTTPException(404, "batch not found or expired")
        return batch

    def _row(batch: Batch, serial: str) -> BatchRow:
        row = batch.row(serial)
        if row is None:
            raise HTTPException(404, f"no row '{serial}' in this batch")
        return row

    def _images_meta(bid: str, row: BatchRow) -> list[dict]:
        return [
            {"index": im.index, "role": im.role, "width": im.width, "height": im.height,
             "url": f"/api/verify/batch/{bid}/rows/{row.serial_number}/images/{im.index}"}
            for im in row.images
        ]

    # ---- routes ----------------------------------------------------

    @router.get("/manifest-template.csv")
    def manifest_template() -> Response:
        return Response(
            content=blank_template(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="manifest.csv"'},
        )

    @router.post("/verify/batch")
    async def create_batch(archive: UploadFile = File(...)) -> dict:
        data = await archive.read()
        if len(data) > MAX_ZIP_BYTES:
            raise HTTPException(413, f"archive exceeds {MAX_ZIP_BYTES // (1024 * 1024)} MB")
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise HTTPException(422, "not a valid ZIP archive") from exc

        names = [n for n in zf.namelist() if not n.endswith("/")]
        manifest_name = next(
            (n for n in sorted(names, key=lambda n: n.count("/"))
             if n.rsplit("/", 1)[-1].lower() == "manifest.csv"), None)
        if manifest_name is None:
            raise HTTPException(422, "no manifest.csv found at the root of the archive")

        rows, missing = parse_manifest(zf.read(manifest_name))
        image_names = [n for n in names if n != manifest_name]
        report = reconcile(rows, image_names)
        report.missing_columns = missing
        if missing:
            report.fatal = None  # not fatal per se, but nothing can proceed
        if not rows and missing:
            batch = store.create([], report)
            return batch.to_dict()
        if len(rows) > MAX_ROWS:
            raise HTTPException(413, f"manifest has {len(rows)} rows; limit is {MAX_ROWS}")

        by_base = {n.rsplit("/", 1)[-1]: n for n in image_names}
        blocked_serials = {d["serial"] for d in report.rows_missing_images}

        batch_rows: list[BatchRow] = []
        for r in rows:
            images: list[StoredImage] = []
            blocked = r.serial_number in blocked_serials or not r.ok
            reason = None
            if not blocked:
                for idx, fname in enumerate(r.image_names):
                    raw = zf.read(by_base[fname])
                    try:
                        with Image.open(io.BytesIO(raw)) as im:
                            w, h = im.size
                    except Exception:  # noqa: BLE001 — any decode failure blocks the row
                        blocked, reason = True, f"'{fname}' is not a readable image"
                        break
                    ext = os.path.splitext(fname)[1].lower()
                    role = ["front", "back", "neck"][idx] if idx < 3 else None
                    images.append(StoredImage(index=idx, role=role,
                                              content_type=_CTYPE.get(ext, "image/png"),
                                              data=raw, width=w, height=h))
            if blocked and reason is None:
                reason = ("; ".join(r.row_errors) if r.row_errors
                          else "referenced image(s) not in the archive")
            batch_rows.append(BatchRow(
                serial_number=r.serial_number, line=r.line,
                fields=None if blocked else r.fields,
                images=[] if blocked else images,
                blocked_reason=reason if blocked else None,
            ))

        batch = store.create(batch_rows, report)
        return batch.to_dict()

    @router.post("/verify/batch/{bid}/start", status_code=202)
    async def start_batch(bid: str) -> dict:
        batch = _get(bid)
        if batch.state != "ready":
            raise HTTPException(409, f"batch is already {batch.state}")
        if not batch.processable:
            raise HTTPException(409, "no processable rows — resolve the pre-flight issues")
        # materialize image bytes to temp files for the OCR subprocess and build
        # the LabelApplication with real paths
        tmp = tempfile.mkdtemp(prefix="ttbbatch_")
        for row in batch.processable:
            refs = []
            for im in row.images:
                p = os.path.join(tmp, f"{row.serial_number}_{im.index}"
                                 + _ext_for(im.content_type))
                with open(p, "wb") as fh:
                    fh.write(im.data)
                refs.append({"path": p, "role": im.role})
            row.application = LabelApplication(images=refs, **row.fields)
        threading.Thread(target=_process, args=(batch,), daemon=True,
                         name=f"batch-{bid}").start()
        return batch.to_dict()

    @router.get("/verify/batch/{bid}")
    def get_batch(bid: str) -> dict:
        return _get(bid).to_dict()

    @router.get("/verify/batch/{bid}/events")
    async def batch_events(bid: str) -> StreamingResponse:
        batch = _get(bid)

        async def gen():
            seen: set[str] = set()
            while True:
                for row in batch.queue_order():
                    if row.status in ("done", "error") and row.serial_number not in seen:
                        seen.add(row.serial_number)
                        yield _sse("row", row.summary())
                yield _sse("progress", batch.progress())
                if batch.state == "complete":
                    yield _sse("done", batch.to_dict())
                    return
                await asyncio.sleep(0.25)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    @router.get("/verify/batch/{bid}/rows/{serial}")
    def get_row(bid: str, serial: str) -> dict:
        batch = _get(bid)
        row = _row(batch, serial)
        unresolved, can_finalize = row.review_state()
        return {
            "serial_number": serial,
            "verdict": row.verdict,
            "status": row.status,
            "blocked_reason": row.blocked_reason,
            "error": row.error,
            "result": row.result.to_dict() if row.result else None,
            "images": _images_meta(bid, row),
            "decisions": row.decisions,
            "unresolved_review_ids": unresolved,
            "can_finalize": can_finalize,
            "finalized": row.finalized,
        }

    @router.get("/verify/batch/{bid}/rows/{serial}/images/{index}")
    def get_row_image(bid: str, serial: str, index: int) -> Response:
        row = _row(_get(bid), serial)
        for im in row.images:
            if im.index == index:
                return Response(content=im.data, media_type=im.content_type,
                                headers={"Cache-Control": "private, max-age=3600"})
        raise HTTPException(404, "image not found")

    @router.post("/verify/batch/{bid}/rows/{serial}/decisions")
    def row_decision(bid: str, serial: str, body: dict) -> dict:
        row = _row(_get(bid), serial)
        check_id = body.get("check_id")
        decision = body.get("decision")
        if decision not in ("accept", "reject"):
            raise HTTPException(422, "decision must be 'accept' or 'reject'")
        check = next((c for c in (row.result.checks if row.result else [])
                      if c.check_id == check_id), None)
        if check is None:
            raise HTTPException(404, f"no check '{check_id}' in this row")
        if check.outcome is not Outcome.REVIEW:
            raise HTTPException(409, f"check '{check_id}' is {check.outcome.value}, "
                                     "not agent-resolvable")
        row.decisions[check_id] = decision
        unresolved, can_finalize = row.review_state()
        return {"decisions": row.decisions, "unresolved_review_ids": unresolved,
                "can_finalize": can_finalize}

    @router.post("/verify/batch/{bid}/rows/{serial}/finalize")
    def row_finalize(bid: str, serial: str, body: dict) -> dict:
        row = _row(_get(bid), serial)
        action = body.get("action")
        if action not in ("approve", "reject", "request_image"):
            raise HTTPException(422, "action must be approve / reject / request_image")
        row.finalized = action
        return {"serial_number": serial, "action": action}

    @router.post("/verify/batch/{bid}/rows/{serial}/draft-notice")
    def row_draft_notice(bid: str, serial: str) -> dict:
        """2.9 use C: draft rejection language for one flagged row.

        Behind an explicit action, so an unused feature costs nothing per label,
        and it runs on findings the rules engine already produced — the model is
        not re-reading the label and cannot introduce a fact the engine didn't
        establish. The agent edits and owns whatever comes back.
        """
        from ttbverify.ai import notice as drafting

        row = _row(_get(bid), serial)
        if not row.result:
            raise HTTPException(409, "this row has no result to write about yet")
        application = {"serial_number": row.serial_number,
                       "brand_name": row.brand_name,
                       **{k: v for k, v in (row.fields or {}).items()
                          if k != "images"}}
        draft, error = drafting.draft(ai, application, row.result.to_dict())
        if draft is None:
            raise HTTPException(503, error or "no draft available")
        return draft.to_dict()

    @router.get("/verify/batch/{bid}/export.csv")
    def export_csv(bid: str) -> Response:
        batch = _get(bid)
        check_ids: list[str] = []
        for row in batch.rows:
            for c in (row.result.checks if row.result else []):
                if c.check_id not in check_ids:
                    check_ids.append(c.check_id)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["serial_number", "line", "verdict", "agent_action",
                    "elapsed_ms", *check_ids])
        for row in batch.queue_order():
            by = {c.check_id: c.outcome.value for c in (row.result.checks if row.result else [])}
            w.writerow([
                row.serial_number, row.line, row.verdict, row.finalized or "",
                row.result.elapsed_ms if row.result else "",
                *[by.get(cid, "") for cid in check_ids],
            ])
        return Response(content=b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8"),
                        media_type="text/csv",
                        headers={"Content-Disposition":
                                 f'attachment; filename="batch_{bid}.csv"'})

    return router


def _ext_for(content_type: str) -> str:
    return {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
            "image/tiff": ".tif"}.get(content_type, ".png")


def _sse(event: str, data) -> str:
    import json

    return f"event: {event}\ndata: {json.dumps(data)}\n\n"
