"""FastAPI application: upload, run, compare, score.

Serves the built React frontend from the same origin, so there is exactly one
Railway service and no CORS configuration to get wrong.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.engines import registry
from app.engines.runner import is_available, run_many
from app.models import (
    DocumentSummary,
    EngineInfo,
    EngineListResponse,
    LayoutRequest,
    RegionRunRequest,
    RunRequest,
    ScoreRequest,
    TemplateApplyRequest,
    TemplateCreateRequest,
    UploadResponse,
)
from app.services import metrics as metrics_service
from app.services import rasterize
from app.services import region_runner
from app.services.store import Store

settings = get_settings()
store = Store(settings.db_path)

logger = logging.getLogger("masterocr")

# How often the retention sweep runs. The sweep itself is cheap (one indexed
# DELETE plus a directory removal per expired document), so an hourly cadence
# keeps the volume bounded without needing a cron service.
RETENTION_SWEEP_INTERVAL_S = 3600


def _purge_expired() -> int:
    """Delete documents past RETENTION_HOURS, including their files on disk.

    The DB rows cascade to pages/runs/results/metrics/scores, but the upload and
    rendered page images live on the volume, so they have to be removed
    explicitly or the volume grows without bound.
    """
    cutoff = time.time() - settings.retention_hours * 3600
    expired = store.expired_documents(cutoff)
    if not expired:
        return 0

    for document in expired:
        # stored_path is <work_dir>/<document_id>/input.pdf
        job_dir = Path(document["stored_path"]).parent
        if job_dir.is_dir() and job_dir.parent == settings.work_dir:
            shutil.rmtree(job_dir, ignore_errors=True)

    removed = store.purge_older_than(cutoff)
    logger.info("retention: purged %d document(s) older than %dh", removed, settings.retention_hours)
    return removed


async def _retention_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(_purge_expired)
        except Exception:  # noqa: BLE001 - a failed sweep must not kill the loop
            logger.exception("retention sweep failed")
        await asyncio.sleep(RETENTION_SWEEP_INTERVAL_S)


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(_retention_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="MasterOCR",
    description="Compare OCR engines on PDF isometrics and schematics.",
    version="0.1.0",
    lifespan=lifespan,
)

# In-memory progress channels: document_id -> asyncio.Queue of events.
_progress: dict[str, asyncio.Queue[dict[str, Any]]] = {}

# Region-run progress channels, keyed by run_id rather than document_id so two
# pages of the same document can run at once without their streams colliding.
_region_progress: dict[str, asyncio.Queue[dict[str, Any]]] = {}


# ---------------------------------------------------------------------------
# Engines
# ---------------------------------------------------------------------------


@app.get("/api/engines", response_model=EngineListResponse)
def list_engines() -> EngineListResponse:
    infos: list[EngineInfo] = []
    for engine in registry.ENGINES:
        available, reason = is_available(engine, settings)
        infos.append(
            EngineInfo(
                id=engine.id,
                name=engine.name,
                vendor=engine.vendor,
                tier=engine.tier,
                kind=engine.kind,
                license=engine.license,
                license_note=engine.license_note,
                output=engine.output,
                cost_per_page_usd=engine.cost_per_page_usd,
                free_tier=engine.free_tier,
                requires_key=engine.requires_key,
                requires_gpu=engine.requires_gpu,
                requires_heavy=engine.requires_heavy,
                notes=engine.notes,
                tags=list(engine.tags),
                available=available,
                unavailable_reason=reason or None,
            )
        )
    return EngineListResponse(
        engines=infos,
        tier_counts={str(k): v for k, v in registry.tier_counts().items()},
        available_count=sum(1 for info in infos if info.available),
    )


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


@app.post("/api/documents", response_model=UploadResponse)
async def upload_document(file: UploadFile = File(...)) -> UploadResponse:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    document_id = uuid.uuid4().hex
    job_dir = settings.work_dir / document_id
    job_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = job_dir / "input.pdf"

    size = 0
    limit = settings.max_upload_mb * 1024 * 1024
    with pdf_path.open("wb") as handle:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                handle.close()
                shutil.rmtree(job_dir, ignore_errors=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"File exceeds {settings.max_upload_mb} MB limit",
                )
            handle.write(chunk)

    try:
        info = rasterize.inspect(
            pdf_path,
            dpi=settings.raster_dpi,
            output_dir=job_dir / "pages",
            max_pages=settings.max_pages,
        )
    except Exception as exc:  # noqa: BLE001 - corrupt PDFs are user error
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"Could not read PDF: {exc}") from exc

    if info.page_count == 0:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="PDF has no pages")

    store.create_document(
        document_id=document_id,
        filename=file.filename,
        size_bytes=size,
        page_count=info.page_count,
        classification=info.classification,
        stored_path=str(pdf_path),
        pages=[
            {
                "number": page.number,
                "classification": page.classification,
                "text_chars": page.text_chars,
                "image_count": page.image_count,
                "vector_paths": page.vector_paths,
                "image_path": str(page.image_path) if page.image_path else None,
                "width_pt": page.width_pt,
                "height_pt": page.height_pt,
            }
            for page in info.pages
        ],
    )

    return UploadResponse(
        document_id=document_id,
        filename=file.filename,
        page_count=info.page_count,
        classification=info.classification,
        pages=[
            {
                "number": page.number,
                "classification": page.classification,
                "text_chars": page.text_chars,
                "image_count": page.image_count,
                "vector_paths": page.vector_paths,
            }
            for page in info.pages
        ],
    )


@app.get("/api/documents", response_model=list[DocumentSummary])
def list_documents() -> list[DocumentSummary]:
    return [
        DocumentSummary(
            id=row["id"],
            filename=row["filename"],
            page_count=row["page_count"],
            classification=row["classification"],
            created_at=row["created_at"],
        )
        for row in store.list_documents()
    ]


@app.get("/api/documents/{document_id}")
def get_document(document_id: str) -> dict[str, Any]:
    document = store.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    document["runs"] = store.get_runs(document_id)
    document["scores"] = store.get_scores(document_id)
    return document


@app.get("/api/documents/{document_id}/pages/{page_number}.png")
def get_page_image(document_id: str, page_number: int) -> FileResponse:
    document = store.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    for page in document["pages"]:
        if page["page_number"] == page_number and page["image_path"]:
            path = Path(page["image_path"])
            if path.exists():
                return FileResponse(path, media_type="image/png")
    raise HTTPException(status_code=404, detail="Page image not found")


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


@app.post("/api/documents/{document_id}/run")
async def start_run(document_id: str, request: RunRequest) -> dict[str, Any]:
    document = store.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    if request.engine_ids:
        selected = []
        for engine_id in request.engine_ids:
            try:
                selected.append(registry.get_engine(engine_id))
            except KeyError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        selected = [e for e in registry.ENGINES if is_available(e, settings)[0]]

    if not selected:
        raise HTTPException(status_code=400, detail="No runnable engines selected")

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    _progress[document_id] = queue

    asyncio.create_task(_execute(document, selected, queue))

    return {
        "document_id": document_id,
        "engine_count": len(selected),
        "engines": [engine.id for engine in selected],
    }


async def _execute(document: dict[str, Any], engines, queue: asyncio.Queue) -> None:
    """Run every engine, persist results, then score them."""
    document_id = document["id"]
    pdf_path = Path(document["stored_path"])
    page_images = [
        Path(page["image_path"])
        for page in document["pages"]
        if page["image_path"]
    ]

    run_ids: dict[str, str] = {}
    for engine in engines:
        run_ids[engine.id] = store.create_run(document_id, engine.id)

    await queue.put(
        {
            "type": "start",
            "total": len(engines),
            "engines": [engine.id for engine in engines],
        }
    )

    completed = 0

    async def on_complete(outcome) -> None:
        nonlocal completed
        completed += 1
        store.finish_run(
            run_ids[outcome.engine_id],
            status="ok" if outcome.ok else "error",
            duration_ms=outcome.duration_ms,
            error=outcome.error,
            meta=outcome.meta,
            pages=outcome.pages,
        )
        await queue.put(
            {
                "type": "engine",
                "engine_id": outcome.engine_id,
                "ok": outcome.ok,
                "duration_ms": outcome.duration_ms,
                "error": outcome.error,
                "completed": completed,
                "total": len(engines),
            }
        )

    outcomes = await run_many(
        engines,
        pdf_path=pdf_path,
        page_images=page_images,
        page_count=document["page_count"],
        settings=settings,
        on_complete=on_complete,
    )

    # --- scoring -----------------------------------------------------
    outputs = {
        outcome.engine_id: outcome.text
        for outcome in outcomes
        if outcome.ok and outcome.text.strip()
    }

    reference_text: str | None = None
    reference_name = "consensus"
    if document["classification"] == "born_digital":
        layer = rasterize.extract_text_layer(pdf_path, max_pages=settings.max_pages)
        joined = "\n\n".join(layer)
        if joined.strip():
            reference_text = joined
            reference_name = "text-layer"

    if outputs:
        report = metrics_service.evaluate(
            outputs, reference_text=reference_text, reference_name=reference_name
        )
        for engine_id, values in report.items():
            store.save_metrics(run_ids[engine_id], values)

    await queue.put({"type": "done", "document_id": document_id})


@app.get("/api/documents/{document_id}/progress")
async def progress(document_id: str) -> StreamingResponse:
    queue = _progress.get(document_id)
    if queue is None:
        raise HTTPException(status_code=404, detail="No active run for this document")

    async def event_stream():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") == "done":
                    break
        finally:
            _progress.pop(document_id, None)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Scores and export
# ---------------------------------------------------------------------------


@app.post("/api/documents/{document_id}/scores")
def save_score(document_id: str, request: ScoreRequest) -> dict[str, Any]:
    if store.get_document(document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found")
    store.save_score(document_id, request.engine_id, request.stars, request.notes)
    return {"ok": True}


@app.get("/api/documents/{document_id}/export.json")
def export_json(document_id: str) -> JSONResponse:
    document = store.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    document["runs"] = store.get_runs(document_id)
    document["scores"] = store.get_scores(document_id)
    return JSONResponse(
        document,
        headers={
            "Content-Disposition": f'attachment; filename="masterocr-{document_id}.json"'
        },
    )


@app.get("/api/documents/{document_id}/export.csv")
def export_csv(document_id: str) -> StreamingResponse:
    document = store.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    runs = store.get_runs(document_id)
    scores = store.get_scores(document_id)

    header = (
        "engine_id,status,duration_ms,cer,wer,word_count,"
        "repetition_ratio,prose_ratio,length_zscore,garbage_ratio,flags,"
        "dimensions_missed,dimensions_invented,stars,error\n"
    )

    def rows():
        yield header
        for run in runs:
            metrics = run.get("metrics") or {}
            hallucination = metrics.get("hallucination") or {}
            dimensions = metrics.get("dimensions") or {}
            score = scores.get(run["engine_id"]) or {}
            flags = "|".join(hallucination.get("flags") or [])
            yield (
                f"{run['engine_id']},{run['status']},{run['duration_ms']},"
                f"{metrics.get('cer', '')},{metrics.get('wer', '')},"
                f"{hallucination.get('word_count', '')},"
                f"{hallucination.get('repetition_ratio', '')},"
                f"{hallucination.get('prose_ratio', '')},"
                f"{hallucination.get('length_zscore', '')},"
                f"{hallucination.get('garbage_ratio', '')},"
                f"{flags},"
                f"{dimensions.get('missed', '')},{dimensions.get('invented', '')},"
                f"{score.get('stars', '')},"
                f"\"{(run.get('error') or '').replace(chr(34), chr(39))}\"\n"
            )

    return StreamingResponse(
        rows(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="masterocr-{document_id}.csv"'
        },
    )


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "engines": len(registry.ENGINES),
        "available": sum(
            1 for engine in registry.ENGINES if is_available(engine, settings)[0]
        ),
        "heavy": settings.install_heavy,
        "time": time.time(),
    }


# ---------------------------------------------------------------------------
# Phase 2: region capture
# ---------------------------------------------------------------------------


def _layout_or_404(document_id: str, page_number: int) -> dict[str, Any]:
    layout = store.get_layout(document_id, page_number)
    if layout is None:
        raise HTTPException(status_code=404, detail="No layout for this page")
    return layout


@app.get("/api/documents/{document_id}/layouts/{page_number}")
def get_layout(document_id: str, page_number: int) -> dict[str, Any]:
    document = store.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    layout = store.get_layout(document_id, page_number)
    if layout is None:
        return {
            "document_id": document_id,
            "page_number": page_number,
            "page_width_pt": 0,
            "page_height_pt": 0,
            "regions": [],
        }
    return layout


@app.put("/api/documents/{document_id}/layouts/{page_number}")
def put_layout(document_id: str, page_number: int, request: LayoutRequest) -> dict[str, Any]:
    document = store.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if request.page_number != page_number:
        raise HTTPException(status_code=400, detail="Page number mismatch")

    store.save_layout(
        document_id,
        page_number,
        page_width_pt=request.page_width_pt,
        page_height_pt=request.page_height_pt,
        regions=[region.model_dump() for region in request.regions],
    )
    return {"ok": True, "region_count": len(request.regions)}


@app.delete("/api/documents/{document_id}/layouts/{page_number}")
def delete_layout(document_id: str, page_number: int) -> dict[str, Any]:
    if store.get_document(document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found")
    removed = store.delete_layout(document_id, page_number)
    return {"ok": True, "removed": removed}


@app.get("/api/documents/{document_id}/pages/{page_number}/grid")
def get_page_grid(document_id: str, page_number: int) -> dict[str, Any]:
    """Detected ruling lines for the whole page, for canvas snapping.

    Returns normalized 0..1 positions so the frontend can map them onto the
    rendered image without knowing the pixel dimensions.
    """
    document = store.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    image_path = next(
        (
            page["image_path"]
            for page in document["pages"]
            if page["page_number"] == page_number and page["image_path"]
        ),
        None,
    )
    if not image_path or not Path(image_path).exists():
        raise HTTPException(status_code=404, detail="Page image not found")

    from PIL import Image

    from app.services import grid as grid_service

    with Image.open(image_path) as image:
        mask = grid_service.to_ink_mask(image)
        height, width = mask.shape
        row_coverage = mask.mean(axis=1)
        col_coverage = mask.mean(axis=0)
        row_lines = grid_service._line_positions(mask, axis=1)
        col_lines = grid_service._line_positions(mask, axis=0)

    return {
        "page_number": page_number,
        "width": width,
        "height": height,
        "row_lines": [round(y / height, 5) for y in row_lines],
        "col_lines": [round(x / width, 5) for x in col_lines],
    }


@app.post("/api/documents/{document_id}/regions/run")
async def start_region_run(
    document_id: str, request: RegionRunRequest
) -> dict[str, Any]:
    document = store.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    layout = store.get_layout(document_id, request.page_number)
    if layout is None or not layout.get("regions"):
        raise HTTPException(status_code=400, detail="No regions defined for this page")

    regions = [
        region
        for region in layout["regions"]
        if region.get("kind") != "ignore"
        and (not request.region_ids or region["id"] in request.region_ids)
    ]
    if not regions:
        raise HTTPException(status_code=400, detail="No runnable regions selected")

    run_id = store.create_region_run(document_id, request.page_number)
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    _region_progress[run_id] = queue

    asyncio.create_task(
        _execute_region_run(
            document=document,
            regions=regions,
            engine_ids=request.engine_ids,
            run_id=run_id,
            queue=queue,
        )
    )

    return {
        "run_id": run_id,
        "document_id": document_id,
        "page_number": request.page_number,
        "region_count": len(regions),
    }


async def _execute_region_run(
    *,
    document: dict[str, Any],
    regions: list[dict[str, Any]],
    engine_ids: list[str],
    run_id: str,
    queue: asyncio.Queue[dict[str, Any]],
) -> None:
    """Run every region, persist results, and stream progress."""
    document_id = document["id"]
    total = len(regions)
    await queue.put({"type": "start", "total": total, "run_id": run_id})

    completed = 0
    failures = 0
    work_dir = settings.work_dir / document_id / "regions"

    async def on_engine_start(region_id: str, engine_id: str) -> None:
        """Tell the UI which engine is grinding so it never looks hung."""
        await queue.put(
            {"type": "engine", "region_id": region_id, "engine_id": engine_id}
        )

    try:
        for region in regions:
            outcomes = await region_runner.run_region(
                region,
                document=document,
                engine_ids=engine_ids,
                settings=settings,
                work_dir=work_dir,
                on_engine_start=lambda engine_id, _rid=region["id"]: on_engine_start(
                    _rid, engine_id
                ),
            )
            for outcome in outcomes:
                store.save_region_result(
                    run_id,
                    outcome.region_id,
                    outcome.engine_id,
                    status="ok" if outcome.ok else "error",
                    duration_ms=outcome.duration_ms,
                    error=outcome.error,
                    result=outcome.result or None,
                )
                if not outcome.ok:
                    failures += 1
            completed += 1
            await queue.put(
                {
                    "type": "region",
                    "region_id": region["id"],
                    "completed": completed,
                    "total": total,
                    "engines": [outcome.engine_id for outcome in outcomes],
                    "ok": all(outcome.ok for outcome in outcomes) if outcomes else True,
                }
            )

        status = "ok" if failures == 0 else "partial"
        store.finish_region_run(run_id, status=status)
        await queue.put(
            {"type": "done", "run_id": run_id, "status": status, "failures": failures}
        )
    except Exception as exc:  # noqa: BLE001 - the run must always finish
        logger.exception("region run %s failed", run_id)
        store.finish_region_run(run_id, status="error", error=f"{type(exc).__name__}: {exc}")
        await queue.put({"type": "done", "run_id": run_id, "status": "error"})


@app.get("/api/documents/{document_id}/regions/runs/{run_id}/progress")
async def region_run_progress(document_id: str, run_id: str) -> StreamingResponse:
    queue = _region_progress.get(run_id)
    if queue is None:
        raise HTTPException(status_code=404, detail="No active region run")

    async def event_stream():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") == "done":
                    break
        finally:
            _region_progress.pop(run_id, None)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/documents/{document_id}/regions/runs/{run_id}")
def get_region_run(document_id: str, run_id: str) -> dict[str, Any]:
    run = store.get_region_run(run_id)
    if run is None or run["document_id"] != document_id:
        raise HTTPException(status_code=404, detail="Region run not found")
    run["results"] = store.get_region_results(run_id)
    return run


@app.get("/api/documents/{document_id}/regions/results")
def get_region_results(document_id: str, page_number: int) -> dict[str, Any]:
    """Results from the most recent finished run for a page."""
    document = store.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    results = store.get_latest_region_results(document_id, page_number)
    return {"document_id": document_id, "page_number": page_number, "results": results}


@app.get("/api/documents/{document_id}/regions/export.json")
def export_regions_json(document_id: str, page_number: int) -> JSONResponse:
    """Combined export: tables as matrices, lines as text, ignore omitted."""
    document = store.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    layout = store.get_layout(document_id, page_number) or {"regions": []}
    results = store.get_latest_region_results(document_id, page_number)

    by_region: dict[str, list[dict[str, Any]]] = {}
    for row in results:
        by_region.setdefault(row["region_id"], []).append(row)

    payload: dict[str, Any] = {
        "document_id": document_id,
        "page_number": page_number,
        "regions": [],
    }
    for region in layout["regions"]:
        if region.get("kind") == "ignore":
            continue
        entry: dict[str, Any] = {
            "id": region["id"],
            "name": region["name"],
            "kind": region["kind"],
            "engines": {},
        }
        for row in by_region.get(region["id"], []):
            entry["engines"][row["engine_id"]] = {
                "status": row["status"],
                "duration_ms": row["duration_ms"],
                "error": row["error"],
                "result": row["result"],
            }
        payload["regions"].append(entry)

    return JSONResponse(
        payload,
        headers={
            "Content-Disposition": f'attachment; filename="regions-{document_id}-p{page_number}.json"'
        },
    )


@app.get("/api/documents/{document_id}/regions/export.csv")
def export_regions_csv(document_id: str, page_number: int) -> StreamingResponse:
    """CSV export: one block per table region, using the first ok engine."""
    document = store.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    layout = store.get_layout(document_id, page_number) or {"regions": []}
    results = store.get_latest_region_results(document_id, page_number)

    by_region: dict[str, list[dict[str, Any]]] = {}
    for row in results:
        by_region.setdefault(row["region_id"], []).append(row)

    def rows():
        for region in layout["regions"]:
            if region.get("kind") == "ignore":
                continue
            candidates = by_region.get(region["id"], [])
            ok_rows = [row for row in candidates if row["status"] == "ok" and row["result"]]
            chosen = ok_rows[0] if ok_rows else None
            yield f"# region: {region['name']} ({region['kind']})\n"
            if chosen is None:
                yield "# (no result)\n\n"
                continue
            result = chosen["result"]
            if result.get("kind") == "table":
                for row in result.get("cells") or []:
                    cells = [
                        str(cell.get("text", "")).replace('"', '""')
                        for cell in row
                    ]
                    yield ",".join(f'"{cell}"' for cell in cells) + "\n"
            else:
                text = result.get("text") or ""
                if result.get("kind") == "keyvalue" and result.get("key"):
                    text = f"{result['key']}: {result.get('value', '')}"
                yield f'"{text.replace(chr(34), chr(39))}"\n'
            yield "\n"

    return StreamingResponse(
        rows(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="regions-{document_id}-p{page_number}.csv"'
        },
    )


# --- templates ---------------------------------------------------------------


@app.get("/api/templates")
def list_templates() -> list[dict[str, Any]]:
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "page_width_pt": row["page_width_pt"],
            "page_height_pt": row["page_height_pt"],
            "region_count": len(row["regions"]),
            "created_at": row["created_at"],
        }
        for row in store.list_templates()
    ]


@app.post("/api/templates")
def create_template(request: TemplateCreateRequest) -> dict[str, Any]:
    layout = store.get_layout(request.document_id, request.page_number)
    if layout is None or not layout.get("regions"):
        raise HTTPException(status_code=400, detail="No layout to save as a template")
    template_id = store.save_template(
        name=request.name,
        page_width_pt=layout["page_width_pt"],
        page_height_pt=layout["page_height_pt"],
        regions=layout["regions"],
    )
    return {"ok": True, "template_id": template_id}


@app.delete("/api/templates/{template_id}")
def delete_template(template_id: str) -> dict[str, Any]:
    removed = store.delete_template(template_id)
    return {"ok": True, "removed": removed}


@app.post("/api/documents/{document_id}/layouts/{page_number}/apply-template/{template_id}")
def apply_template(
    document_id: str, page_number: int, template_id: str
) -> dict[str, Any]:
    document = store.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    template = store.get_template(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")

    page = next(
        (
            page
            for page in document["pages"]
            if page["page_number"] == page_number
        ),
        None,
    )
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")

    # Regions are normalized 0..1, so they port across page sizes as-is. The
    # stored page dimensions are updated to the target page so later edits
    # keep their frame of reference.
    regions = [dict(region) for region in template["regions"]]
    for region in regions:
        region["page_number"] = page_number

    store.save_layout(
        document_id,
        page_number,
        page_width_pt=page.get("width_pt") or template["page_width_pt"],
        page_height_pt=page.get("height_pt") or template["page_height_pt"],
        regions=regions,
    )
    return {"ok": True, "region_count": len(regions)}


# ---------------------------------------------------------------------------
# Static frontend (mounted last so /api wins)
# ---------------------------------------------------------------------------

if settings.frontend_dist.exists():
    app.mount(
        "/",
        StaticFiles(directory=settings.frontend_dist, html=True),
        name="frontend",
    )
