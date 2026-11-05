"""Executes engine adapters as isolated subprocesses.

Isolation matters here: PaddleOCR can segfault, Docling can exhaust memory, and
a cloud adapter can hang on a socket. None of those may take down the web
request, so every engine runs in its own process with a hard timeout.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import Settings
from app.engines.registry import Engine

ENGINES_ROOT = Path(__file__).resolve().parents[3] / "engines"


@dataclass
class RunOutcome:
    engine_id: str
    ok: bool
    duration_ms: int
    pages: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    stderr: str = ""
    exit_code: int | None = None
    timed_out: bool = False

    @property
    def text(self) -> str:
        """Concatenated best-text across pages, used by the metrics layer."""
        chunks: list[str] = []
        for page in self.pages:
            chunks.append(
                page.get("markdown") or page.get("text") or page.get("html") or ""
            )
        return "\n\n".join(chunk for chunk in chunks if chunk)


def adapter_path(engine_id: str) -> Path:
    return ENGINES_ROOT / engine_id / "run.py"


def is_available(engine: Engine, settings: Settings) -> tuple[bool, str]:
    """Decide whether an engine can run in this deployment.

    Returns (available, reason_if_not).
    """
    if engine.requires_gpu:
        return False, "GPU-only engine; Railway provides CPU containers only"
    if engine.requires_heavy and not settings.install_heavy:
        return False, "Heavy engine; rebuild with INSTALL_HEAVY=true to enable"
    if engine.requires_key:
        if not getattr(settings, engine.requires_key, None):
            return False, f"Missing credential: {engine.requires_key}"
    if not adapter_path(engine.id).exists():
        return False, "Adapter not implemented yet"
    return True, ""


def _credentials_for(engine: Engine, settings: Settings) -> dict[str, str]:
    """Pass only the credential this engine needs, never the whole config."""
    if not engine.requires_key:
        return {}
    value = getattr(settings, engine.requires_key, None)
    return {engine.requires_key: value} if value else {}


async def run_engine(
    engine: Engine,
    *,
    pdf_path: Path,
    page_images: list[Path],
    page_count: int,
    settings: Settings,
    options: dict[str, Any] | None = None,
) -> RunOutcome:
    """Run one engine adapter and normalise its output."""
    started = time.perf_counter()

    available, reason = is_available(engine, settings)
    if not available:
        return RunOutcome(
            engine_id=engine.id,
            ok=False,
            duration_ms=0,
            error=reason,
        )

    request = {
        "engine_id": engine.id,
        "pdf_path": str(pdf_path),
        "page_images": [str(path) for path in page_images],
        "page_count": page_count,
        "dpi": settings.raster_dpi,
        "options": options or {},
        "credentials": _credentials_for(engine, settings),
    }

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONPATH"] = str(ENGINES_ROOT.parent / "backend")

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(adapter_path(engine.id)),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    timed_out = False
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(json.dumps(request).encode("utf-8")),
            timeout=engine.timeout_s,
        )
    except asyncio.TimeoutError:
        timed_out = True
        proc.kill()
        stdout, stderr = await proc.communicate()

    duration_ms = int((time.perf_counter() - started) * 1000)
    stderr_text = stderr.decode("utf-8", errors="replace")[-4000:]

    if timed_out:
        return RunOutcome(
            engine_id=engine.id,
            ok=False,
            duration_ms=duration_ms,
            error=f"Timed out after {engine.timeout_s}s",
            stderr=stderr_text,
            exit_code=proc.returncode,
            timed_out=True,
        )

    raw = stdout.decode("utf-8", errors="replace").strip()
    if not raw:
        return RunOutcome(
            engine_id=engine.id,
            ok=False,
            duration_ms=duration_ms,
            error=f"Adapter produced no output (exit {proc.returncode})",
            stderr=stderr_text,
            exit_code=proc.returncode,
        )

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return RunOutcome(
            engine_id=engine.id,
            ok=False,
            duration_ms=duration_ms,
            error=f"Adapter emitted invalid JSON: {exc}",
            stderr=stderr_text,
            exit_code=proc.returncode,
        )

    return RunOutcome(
        engine_id=engine.id,
        ok=bool(payload.get("ok")),
        duration_ms=duration_ms,
        pages=payload.get("pages") or [],
        meta=payload.get("meta") or {},
        error=payload.get("error"),
        stderr=stderr_text,
        exit_code=proc.returncode,
    )


async def run_many(
    engines: list[Engine],
    *,
    pdf_path: Path,
    page_images: list[Path],
    page_count: int,
    settings: Settings,
    on_complete=None,
) -> list[RunOutcome]:
    """Run engines with bounded concurrency, reporting each as it finishes."""
    semaphore = asyncio.Semaphore(settings.max_concurrent_engines)
    results: list[RunOutcome] = []

    async def _one(engine: Engine) -> None:
        async with semaphore:
            outcome = await run_engine(
                engine,
                pdf_path=pdf_path,
                page_images=page_images,
                page_count=page_count,
                settings=settings,
            )
        results.append(outcome)
        if on_complete is not None:
            await on_complete(outcome)

    await asyncio.gather(*(_one(engine) for engine in engines))
    return results


def binary_available(name: str) -> bool:
    """Check for a CLI binary on PATH (poppler, tesseract, mutool, ...)."""
    return shutil.which(name) is not None
