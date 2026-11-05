"""Orchestrates OCR runs over regions.

The design constraint that shaped this module: `run_engine()` in
`app.engines.runner` already accepts `page_images: list[Path]` and
`page_count`, and every adapter loops over that list emitting one PageResult
per image. So:

- **Cell OCR needs zero adapter changes.** All cell crops of a table region are
  passed as "pages" in a single subprocess invocation. One subprocess per
  engine per region, not per cell.
- **Whole-table engines need zero adapter changes.** camelot, Docling, and
  Azure take `pdf_path`, so we hand them a synthetic one-page PDF clipped to
  the region (see `regions.build_region_pdf`).
- **Capability probe.** After a cell run, if the adapter returned fewer pages
  than we sent crops, it ignored `page_images` (text-layer engines do). We
  then fall back to parsing its whole-region output as a matrix. This removes
  the need for a per-engine capability table that would drift out of date.

Everything here is ``async`` because `run_engine` is async and the API calls
this from a running event loop.

Every result is normalized to one shape::

    {
      "kind": "table" | "text" | "keyvalue",
      "rows": int, "cols": int,            # tables only
      "cells": [[{text, confidence, status, ink}]],   # tables only
      "text": str,                          # line/text/keyvalue regions
      "key": str, "value": str,             # keyvalue regions only
      "method": str,                        # how the result was produced
    }
"""

from __future__ import annotations

import logging
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from app.config import Settings
from app.engines import registry
from app.engines.runner import is_available, run_engine
from app.services import grid as grid_service
from app.services import regions as region_service
from app.services import tableparse

logger = logging.getLogger("masterocr.regions")

# Engine kinds that read a text layer or parse document structure. These are
# run whole-region against the clipped PDF rather than cell by cell.
WHOLE_REGION_KINDS = {"text-layer", "table", "docparse"}

# Default engines when a region does not name any. The registry exposes
# Tesseract as PSM variants; `tesseract-psm11` (sparse text) is the closest
# page-level mode, and we additionally pass `psm: 7` in options so the base
# adapter segments the crop as a single line. RapidOCR is the strongest CPU
# engine on the corpus.
DEFAULT_TABLE_ENGINES = ["tesseract-psm11", "rapidocr"]
DEFAULT_LINE_ENGINES = ["tesseract-psm11", "rapidocr"]

# PSM passed to Tesseract for cell crops. Cells are single lines; the
# page-level PSM 3/11 the adapters default to would mis-segment a crop.
CELL_PSM = 7

# Cell-OCR subprocess timeout scaling. One subprocess handles N cell crops,
# so the budget is per-cell cost x N plus a fixed startup allowance. The
# per-cell figure is generous (slow CPU hosts like Railway run ~10x slower
# than a dev machine) — the timeout is a hang guard, not a speed target.
CELL_TIMEOUT_PER_CELL = 8  # seconds per cell crop
CELL_TIMEOUT_BASE = 60  # subprocess startup + model load


@dataclass
class RegionOutcome:
    """Normalized result for one (region, engine) pair."""

    region_id: str
    engine_id: str
    ok: bool
    duration_ms: int
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "region_id": self.region_id,
            "engine_id": self.engine_id,
            "ok": self.ok,
            "duration_ms": self.duration_ms,
            "result": self.result,
            "error": self.error,
        }


def _resolve_engines(
    region: dict[str, Any], engine_ids: list[str], settings: Settings
) -> list[Any]:
    """Engines to run for one region, filtered to what is actually runnable."""
    requested = engine_ids or region.get("engines") or []
    if not requested:
        requested = (
            DEFAULT_LINE_ENGINES
            if region.get("kind") in ("line", "keyvalue", "text")
            else DEFAULT_TABLE_ENGINES
        )
    engines: list[Any] = []
    for engine_id in requested:
        try:
            engine = registry.get_engine(engine_id)
        except KeyError:
            logger.warning("region run: unknown engine %s skipped", engine_id)
            continue
        available, _ = is_available(engine, settings)
        if available:
            engines.append(engine)
    return engines


def _page_size_pt(document: dict[str, Any], page_number: int) -> tuple[float, float]:
    """Page dimensions in points, from the stored page rows."""
    for page in document.get("pages") or []:
        if page.get("page_number") == page_number:
            return (
                float(page.get("width_pt") or 0),
                float(page.get("height_pt") or 0),
            )
    return (0.0, 0.0)


def _page_image_path(document: dict[str, Any], page_number: int) -> Path | None:
    for page in document.get("pages") or []:
        if page.get("page_number") == page_number and page.get("image_path"):
            return Path(page["image_path"])
    return None


def _cols_of(scaffold: list[list[dict[str, Any]]]) -> int:
    return len(scaffold[0]) if scaffold else 0


# ---------------------------------------------------------------------------
# Table regions
# ---------------------------------------------------------------------------


async def _run_table_region(
    region: dict[str, Any],
    engines: list[Any],
    *,
    crop: Image.Image,
    pdf_path: Path,
    page_number: int,
    page_size_pt: tuple[float, float],
    region_bbox_px: tuple[int, int, int, int],
    work_dir: Path,
    floor: float,
    on_engine_start: Any | None = None,
) -> list[RegionOutcome]:
    """Run every engine against one table region."""
    manual_rows = [float(v) for v in (region.get("manual_rows") or [])]
    manual_cols = [float(v) for v in (region.get("manual_cols") or [])]
    grid_result = grid_service.detect_grid(
        crop, manual_rows=manual_rows, manual_cols=manual_cols
    )
    scaffold = region_service.build_cell_matrix(crop, grid_result, floor=floor)
    cell_count = grid_result.rows * grid_result.cols

    outcomes: list[RegionOutcome] = []
    for engine in engines:
        started = time.perf_counter()
        try:
            if engine.kind in WHOLE_REGION_KINDS:
                outcome = await _run_whole_table(
                    engine,
                    pdf_path=pdf_path,
                    page_number=page_number,
                    page_size_pt=page_size_pt,
                    region_bbox_px=region_bbox_px,
                    work_dir=work_dir,
                )
            else:
                outcome = await _run_cell_ocr(
                    engine,
                    crop=crop,
                    scaffold=scaffold,
                    cell_count=cell_count,
                    floor=floor,
                    on_engine_start=on_engine_start,
                )
        except Exception as exc:  # noqa: BLE001 - one engine failing is not fatal
            logger.exception("region %s: engine %s crashed", region["id"], engine.id)
            outcome = RegionOutcome(
                region_id=region["id"],
                engine_id=engine.id,
                ok=False,
                duration_ms=int((time.perf_counter() - started) * 1000),
                error=f"{type(exc).__name__}: {exc}",
            )
        outcome.region_id = region["id"]
        outcomes.append(outcome)
    return outcomes


async def _run_cell_ocr(
    engine: Any,
    *,
    crop: Image.Image,
    scaffold: list[list[dict[str, Any]]],
    cell_count: int,
    floor: float,
    on_engine_start: Any | None = None,
) -> RegionOutcome:
    """OCR every cell crop through one engine in a single subprocess."""
    started = time.perf_counter()
    cols = _cols_of(scaffold)

    with tempfile.TemporaryDirectory(prefix="region-cells-") as tmp:
        tmp_path = Path(tmp)
        flat: list[tuple[int, int, Path]] = []
        for row in scaffold:
            for cell in row:
                bbox = tuple(cell["bbox"])
                cell_image = region_service.crop_cell(crop, bbox)
                path = tmp_path / f"cell_r{cell['row']:03d}c{cell['col']:03d}.png"
                cell_image.save(path)
                flat.append((cell["row"], cell["col"], path))

        if on_engine_start is not None:
            await on_engine_start(engine.id)

        # The page-level timeout covers ONE page. A cell run processes N
        # crops in a single subprocess, so scale the budget with the cell
        # count: per-cell cost x N, plus a fixed startup allowance.
        scaled_timeout = max(engine.timeout_s, CELL_TIMEOUT_PER_CELL * len(flat) + CELL_TIMEOUT_BASE)
        outcome = await run_engine(
            engine,
            pdf_path=tmp_path / "cells.pdf",
            page_images=[path for _, _, path in flat],
            page_count=len(flat),
            settings=_settings(),
            options={"psm": CELL_PSM},
            timeout_s=scaled_timeout,
        )

    duration_ms = int((time.perf_counter() - started) * 1000)

    if not outcome.ok:
        return RegionOutcome(
            region_id="",
            engine_id=engine.id,
            ok=False,
            duration_ms=duration_ms,
            error=outcome.error,
        )

    # Capability probe: an adapter that ignored page_images returns fewer
    # pages than crops sent. Fall back to parsing its output as a whole table.
    if len(outcome.pages) < len(flat):
        text = "\n".join(
            page.get("markdown") or page.get("text") or page.get("html") or ""
            for page in outcome.pages
        )
        matrix = tableparse.to_matrix(text)
        if matrix:
            return _matrix_outcome(
                engine.id, matrix, duration_ms, method="whole-region-fallback"
            )
        return RegionOutcome(
            region_id="",
            engine_id=engine.id,
            ok=False,
            duration_ms=duration_ms,
            error="Engine ignored cell crops and produced no parseable table",
        )

    # Normal path: one PageResult per crop, sent in row-major order.
    for row, col, _ in flat:
        index = row * cols + col
        if index >= len(outcome.pages):
            continue
        page = outcome.pages[index]
        text = page.get("text") or page.get("markdown") or ""
        confidence = page.get("confidence")
        region_service.fill_cell(scaffold[row][col], text, confidence, floor=floor)

    return RegionOutcome(
        region_id="",
        engine_id=engine.id,
        ok=True,
        duration_ms=duration_ms,
        result=_table_result(scaffold, method="cell-ocr"),
    )


async def _run_whole_table(
    engine: Any,
    *,
    pdf_path: Path,
    page_number: int,
    page_size_pt: tuple[float, float],
    region_bbox_px: tuple[int, int, int, int],
    work_dir: Path,
) -> RegionOutcome:
    """Run a whole-table engine against a clipped one-page PDF."""
    started = time.perf_counter()
    work_dir.mkdir(parents=True, exist_ok=True)
    region_pdf = work_dir / f"region-{engine.id}.pdf"

    width_px = max(1, region_bbox_px[2] - region_bbox_px[0])
    height_px = max(1, region_bbox_px[3] - region_bbox_px[1])
    width_pt, height_pt = page_size_pt
    if not width_pt or not height_pt:
        return RegionOutcome(
            region_id="",
            engine_id=engine.id,
            ok=False,
            duration_ms=0,
            error="Page dimensions unknown; cannot clip region",
        )
    bbox_pt = region_service.pixels_to_points(
        region_bbox_px, width_px, height_px, width_pt, height_pt
    )
    region_service.build_region_pdf(pdf_path, page_number, bbox_pt, region_pdf)

    outcome = await run_engine(
        engine,
        pdf_path=region_pdf,
        page_images=[],
        page_count=1,
        settings=_settings(),
        options={},
    )
    duration_ms = int((time.perf_counter() - started) * 1000)

    if not outcome.ok:
        return RegionOutcome(
            region_id="",
            engine_id=engine.id,
            ok=False,
            duration_ms=duration_ms,
            error=outcome.error,
        )

    text = "\n".join(
        page.get("markdown") or page.get("text") or page.get("html") or ""
        for page in outcome.pages
    )
    matrix = tableparse.to_matrix(text)
    if not matrix:
        return RegionOutcome(
            region_id="",
            engine_id=engine.id,
            ok=False,
            duration_ms=duration_ms,
            error="Engine produced no parseable table",
        )
    return _matrix_outcome(engine.id, matrix, duration_ms, method="whole-region")


def _matrix_outcome(
    engine_id: str, matrix: list[list[str]], duration_ms: int, *, method: str
) -> RegionOutcome:
    """Build an outcome from a plain string matrix (whole-table path)."""
    cells = [
        [
            {
                "row": r,
                "col": c,
                "text": value,
                "confidence": None,
                "ink": None,
                "status": "ok" if value.strip() else "blank",
            }
            for c, value in enumerate(row)
        ]
        for r, row in enumerate(matrix)
    ]
    return RegionOutcome(
        region_id="",
        engine_id=engine_id,
        ok=True,
        duration_ms=duration_ms,
        result={
            "kind": "table",
            "rows": len(matrix),
            "cols": max((len(row) for row in matrix), default=0),
            "cells": cells,
            "text": tableparse.matrix_to_markdown(matrix),
            "method": method,
        },
    )


def _table_result(
    scaffold: list[list[dict[str, Any]]], *, method: str
) -> dict[str, Any]:
    """Normalized table result from a filled cell scaffold."""
    matrix = region_service.matrix_to_strings(scaffold)
    return {
        "kind": "table",
        "rows": len(scaffold),
        "cols": _cols_of(scaffold),
        "cells": scaffold,
        "text": tableparse.matrix_to_markdown(matrix),
        "method": method,
    }


# ---------------------------------------------------------------------------
# Text / line / key-value regions
# ---------------------------------------------------------------------------


async def _run_text_region(
    region: dict[str, Any],
    engines: list[Any],
    *,
    crop: Image.Image,
    on_engine_start: Any | None = None,
) -> list[RegionOutcome]:
    """Run OCR on a line, text, or key-value region."""
    outcomes: list[RegionOutcome] = []
    for engine in engines:
        if on_engine_start is not None:
            await on_engine_start(engine.id)
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="region-text-") as tmp:
            crop_path = Path(tmp) / "region.png"
            crop.save(crop_path)
            outcome = await run_engine(
                engine,
                pdf_path=crop_path.with_suffix(".pdf"),
                page_images=[crop_path],
                page_count=1,
                settings=_settings(),
                options={"psm": 7 if region.get("kind") == "line" else 3},
            )
        duration_ms = int((time.perf_counter() - started) * 1000)

        if not outcome.ok:
            outcomes.append(
                RegionOutcome(
                    region_id=region["id"],
                    engine_id=engine.id,
                    ok=False,
                    duration_ms=duration_ms,
                    error=outcome.error,
                )
            )
            continue

        text = "\n".join(
            page.get("text") or page.get("markdown") or page.get("html") or ""
            for page in outcome.pages
        ).strip()
        confidence = next(
            (
                page.get("confidence")
                for page in outcome.pages
                if page.get("confidence") is not None
            ),
            None,
        )
        result: dict[str, Any] = {"kind": "text", "text": text}
        if region.get("kind") == "keyvalue":
            key, value = region_service.split_key_value(text)
            result.update(kind="keyvalue", key=key, value=value)
        outcomes.append(
            RegionOutcome(
                region_id=region["id"],
                engine_id=engine.id,
                ok=True,
                duration_ms=duration_ms,
                result=result,
            )
        )
    return outcomes


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _settings() -> Settings:
    from app.config import get_settings

    return get_settings()


async def run_region(
    region: dict[str, Any],
    *,
    document: dict[str, Any],
    engine_ids: list[str],
    settings: Settings,
    work_dir: Path,
    floor: float = region_service.DEFAULT_CONFIDENCE_FLOOR,
    on_engine_start: Any | None = None,
) -> list[RegionOutcome]:
    """Run every engine against one region and return normalized outcomes."""
    kind = region.get("kind")
    if kind == "ignore":
        return []

    page_number = int(region.get("page_number") or 1)
    page_image_path = _page_image_path(document, page_number)
    if page_image_path is None:
        return [
            RegionOutcome(
                region_id=region["id"],
                engine_id="",
                ok=False,
                duration_ms=0,
                error=f"No rendered image for page {page_number}",
            )
        ]

    engines = _resolve_engines(region, engine_ids, settings)
    if not engines:
        return [
            RegionOutcome(
                region_id=region["id"],
                engine_id="",
                ok=False,
                duration_ms=0,
                error="No runnable engines selected",
            )
        ]

    with Image.open(page_image_path) as page_image:
        bbox = region_service.normalized_to_pixels(
            region, page_image.width, page_image.height
        )
        crop = region_service.crop_region(page_image, bbox)

    if kind == "table":
        return await _run_table_region(
            region,
            engines,
            crop=crop,
            pdf_path=Path(document["stored_path"]),
            page_number=page_number,
            page_size_pt=_page_size_pt(document, page_number),
            region_bbox_px=bbox,
            work_dir=work_dir,
            floor=floor,
            on_engine_start=on_engine_start,
        )
    return await _run_text_region(region, engines, crop=crop, on_engine_start=on_engine_start)
