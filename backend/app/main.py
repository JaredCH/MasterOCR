"""FastAPI application: upload, run, compare, score.

Serves the built React frontend from the same origin, so there is exactly one
Railway service and no CORS configuration to get wrong.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
import uuid
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
    RunRequest,
    ScoreRequest,
    UploadResponse,
)
from app.services import metrics as metrics_service
from app.services import rasterize
from app.services.store import Store

settings = get_settings()
store = Store(settings.db_path)

app = FastAPI(
    title="MasterOCR",
    description="Compare OCR engines on PDF isometrics and schematics.",
    version="0.1.0",
)

# In-memory progress channels: document_id -> asyncio.Queue of events.
_progress: dict[str, asyncio.Queue[dict[str, Any]]] = {}


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
# Static frontend (mounted last so /api wins)
# ---------------------------------------------------------------------------

if settings.frontend_dist.exists():
    app.mount(
        "/",
        StaticFiles(directory=settings.frontend_dist, html=True),
        name="frontend",
    )
