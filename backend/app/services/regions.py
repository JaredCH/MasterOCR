"""Region geometry, cropping, and cell classification.

A *region* is a named rectangle on a page, tagged with a kind:

``table``     a grid of cells; the output is a matrix
``line``      one row of text (a title-block field)
``text``      a multi-line block (notes, paragraphs)
``keyvalue``  a label and its value, split on the first colon or wide gutter
``ignore``    excluded from every output

Coordinates are stored **normalized 0..1** relative to the page, not in pixels.
That is what lets a layout saved on one sheet be applied to another sheet of a
different size, which is the whole point of templates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from PIL import Image

from app.services import grid as grid_service

RegionKind = Literal["table", "line", "text", "keyvalue", "ignore"]

REGION_KINDS: tuple[str, ...] = ("table", "line", "text", "keyvalue", "ignore")

# A cell whose OCR text is shorter than this, or whose mean confidence is below
# the floor, is treated as empty rather than as a failed read.
MIN_TEXT_CHARS = 1
DEFAULT_CONFIDENCE_FLOOR = 0.35

# A cell with less ink than this is visually empty. Used to distinguish "the
# table has a blank here" from "OCR failed on a cell that has content".
EMPTY_INK_RATIO = 0.004

# Padding added around a cell crop before OCR. Tesseract does noticeably worse
# on text that touches the crop border.
CELL_PADDING_PX = 4

# Pixels shaved off each side of a cell before measuring its ink ratio. Cell
# bboxes border on the ruling lines, so without this inset the lines themselves
# count as ink and blank cells get misclassified as "low".
INK_INSET_PX = 3


def _inset(
    bbox: tuple[int, int, int, int], amount: int
) -> tuple[int, int, int, int]:
    """Shrink a bbox by `amount` on every side, keeping it non-degenerate."""
    x0, y0, x1, y1 = bbox
    return (
        x0 + amount,
        y0 + amount,
        max(x0 + amount + 1, x1 - amount),
        max(y0 + amount + 1, y1 - amount),
    )


@dataclass
class Region:
    """One named rectangle on a page."""

    id: str
    name: str
    kind: RegionKind
    x0: float
    y0: float
    x1: float
    y1: float
    page_number: int = 1
    engines: list[str] = field(default_factory=list)
    manual_rows: list[float] = field(default_factory=list)
    manual_cols: list[float] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "x0": self.x0,
            "y0": self.y0,
            "x1": self.x1,
            "y1": self.y1,
            "page_number": self.page_number,
            "engines": list(self.engines),
            "manual_rows": list(self.manual_rows),
            "manual_cols": list(self.manual_cols),
            "options": dict(self.options),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Region":
        return cls(
            id=str(data["id"]),
            name=str(data.get("name") or "Region"),
            kind=data.get("kind") or "table",
            x0=float(data["x0"]),
            y0=float(data["y0"]),
            x1=float(data["x1"]),
            y1=float(data["y1"]),
            page_number=int(data.get("page_number") or 1),
            engines=list(data.get("engines") or []),
            manual_rows=[float(v) for v in (data.get("manual_rows") or [])],
            manual_cols=[float(v) for v in (data.get("manual_cols") or [])],
            options=dict(data.get("options") or {}),
        )


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def clamp_normalized(value: float) -> float:
    return max(0.0, min(1.0, value))


def normalized_to_pixels(
    region: Region | dict[str, Any], width: int, height: int
) -> tuple[int, int, int, int]:
    """Convert a normalized region (dataclass or dict) to a pixel bbox."""
    if isinstance(region, dict):
        x0n, y0n, x1n, y1n = (
            float(region["x0"]),
            float(region["y0"]),
            float(region["x1"]),
            float(region["y1"]),
        )
    else:
        x0n, y0n, x1n, y1n = region.x0, region.y0, region.x1, region.y1
    x0 = int(round(clamp_normalized(min(x0n, x1n)) * width))
    y0 = int(round(clamp_normalized(min(y0n, y1n)) * height))
    x1 = int(round(clamp_normalized(max(x0n, x1n)) * width))
    y1 = int(round(clamp_normalized(max(y0n, y1n)) * height))
    # Guarantee at least one pixel in each direction.
    x1 = max(x1, x0 + 1)
    y1 = max(y1, y0 + 1)
    return x0, y0, min(x1, width), min(y1, height)


def crop_region(image: Image.Image, bbox: tuple[int, int, int, int]) -> Image.Image:
    """Crop a pixel bbox out of a page image."""
    return image.crop(bbox)


def crop_cell(
    crop: Image.Image, bbox: tuple[int, int, int, int], *, padding: int = CELL_PADDING_PX
) -> Image.Image:
    """Crop one cell out of a region crop, with a little padding.

    Padding is clamped to the crop bounds so edge cells do not get a black
    border from PIL's out-of-bounds fill.
    """
    x0, y0, x1, y1 = bbox
    left = max(0, x0 - padding)
    top = max(0, y0 - padding)
    right = min(crop.width, x1 + padding)
    bottom = min(crop.height, y1 + padding)
    return crop.crop((left, top, right, bottom))


# ---------------------------------------------------------------------------
# Cell classification
# ---------------------------------------------------------------------------


def classify_cell(
    text: str | None,
    confidence: float | None,
    ink: float,
    *,
    floor: float = DEFAULT_CONFIDENCE_FLOOR,
) -> str:
    """Decide whether a cell is ``ok``, ``low``, or ``blank``.

    The rule the user chose: a cell is blank when OCR returns no text above the
    confidence floor. A cell that has ink but produced nothing is *not* silently
    blank — it is flagged ``low`` so the failure is visible rather than looking
    like a legitimate empty cell.
    """
    cleaned = (text or "").strip()
    has_ink = ink > EMPTY_INK_RATIO

    if not cleaned:
        # No text at all. If there is ink, OCR missed something.
        return "low" if has_ink else "blank"

    if len(cleaned) < MIN_TEXT_CHARS:
        return "low" if has_ink else "blank"

    if confidence is not None and confidence < floor:
        return "low"

    return "ok"


def build_cell_matrix(
    crop: Image.Image,
    grid_result: grid_service.GridResult,
    *,
    floor: float = DEFAULT_CONFIDENCE_FLOOR,
) -> list[list[dict[str, Any]]]:
    """Build the empty cell scaffold for a table region.

    Every cell exists up front with ``text=""`` and ``status="blank"``. The
    runner fills in text and confidence as OCR results arrive. Building the
    scaffold first is what guarantees blank cells survive to the output.
    """
    matrix: list[list[dict[str, Any]]] = []
    for r in range(grid_result.rows):
        row: list[dict[str, Any]] = []
        for c in range(grid_result.cols):
            bbox = (
                grid_result.col_edges[c],
                grid_result.row_edges[r],
                grid_result.col_edges[c + 1],
                grid_result.row_edges[r + 1],
            )
            # Ink is measured on the *unpadded* cell, inset past the ruling
            # lines. The cell bbox borders sit on the rules themselves, so
            # without the inset every cell would read ~5% ink from the grid
            # lines and a genuinely blank cell would be flagged "low".
            ink = grid_service.ink_ratio(crop.crop(_inset(bbox, INK_INSET_PX)))
            cell_image = crop_cell(crop, bbox)
            row.append(
                {
                    "row": r,
                    "col": c,
                    "bbox": list(bbox),
                    "text": "",
                    "confidence": None,
                    "ink": round(ink, 4),
                    "status": "blank",
                }
            )
        matrix.append(row)
    return matrix


def fill_cell(
    cell: dict[str, Any],
    text: str | None,
    confidence: float | None,
    *,
    floor: float = DEFAULT_CONFIDENCE_FLOOR,
) -> None:
    """Apply an OCR result to a scaffolded cell, in place."""
    cell["text"] = (text or "").strip()
    cell["confidence"] = confidence
    cell["status"] = classify_cell(
        cell["text"], confidence, float(cell.get("ink") or 0.0), floor=floor
    )


def matrix_to_strings(matrix: list[list[dict[str, Any]]]) -> list[list[str]]:
    """Reduce a cell matrix to plain strings for export and comparison."""
    return [[cell.get("text", "") for cell in row] for row in matrix]


# ---------------------------------------------------------------------------
# Key-value splitting
# ---------------------------------------------------------------------------


def split_key_value(text: str) -> tuple[str, str]:
    """Split a key-value region's text into (key, value).

    Prefers the first colon; falls back to the first run of two or more spaces,
    which is how title blocks usually separate a label from its value.
    """
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return "", ""

    for separator in (":", "="):
        if separator in cleaned:
            key, _, value = cleaned.partition(separator)
            return key.strip(), value.strip()

    parts = cleaned.split("  ")
    if len(parts) >= 2:
        return parts[0].strip(), " ".join(parts[1:]).strip()

    # Last resort: split on the widest single space, keeping the value intact.
    if " " in cleaned:
        key, _, value = cleaned.partition(" ")
        return key.strip(), value.strip()

    return cleaned, ""


# ---------------------------------------------------------------------------
# Region PDF (for whole-table engines)
# ---------------------------------------------------------------------------


def build_region_pdf(
    pdf_path: Path,
    page_number: int,
    bbox_pt: tuple[float, float, float, float],
    output_path: Path,
) -> Path:
    """Write a one-page PDF containing only the region, for table engines.

    camelot, Docling, and Azure all take a PDF rather than an image. Rather than
    teach each adapter about regions, we hand them a PDF that *is* the region.
    The clip rectangle is in PDF points, so the caller converts from pixels.
    """
    import pymupdf

    pdf_path = Path(pdf_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(pdf_path) as source:
        source_page = source.load_page(page_number - 1)
        clip = pymupdf.Rect(*bbox_pt)
        # Intersect with the page so an out-of-range region cannot raise.
        clip = clip & source_page.rect
        with pymupdf.open() as target:
            new_page = target.new_page(width=clip.width, height=clip.height)
            new_page.show_pdf_page(new_page.rect, source, page_number - 1, clip=clip)
            target.save(output_path)
    return output_path


def pixels_to_points(
    bbox_px: tuple[int, int, int, int], width_px: int, height_px: int,
    width_pt: float, height_pt: float,
) -> tuple[float, float, float, float]:
    """Scale a pixel bbox on a rendered page back to PDF points."""
    sx = width_pt / width_px if width_px else 1.0
    sy = height_pt / height_px if height_px else 1.0
    x0, y0, x1, y1 = bbox_px
    return (x0 * sx, y0 * sy, x1 * sx, y1 * sy)
