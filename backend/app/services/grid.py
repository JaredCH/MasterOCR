"""Table grid detection: turn a cropped region into row and column edges.

The whole point of phase 2 is that a table region must come back as a *grid*,
not as a blob of text. That means we need to know where the cells are before we
OCR anything, because a cell that contains nothing still has to appear in the
output as an empty cell in the right column.

Two strategies, tried in order:

1. **Ruling lines.** BOM tables and title blocks are almost always drawn with
   actual lines. We threshold the crop, then look for rows and columns whose ink
   coverage is close to 100% across the region. Those are the rules. This is the
   accurate path and it is what makes blank cells work.

2. **Whitespace projection.** Borderless tables (and CAD plots where the rules
   are hairlines that vanish at 300 DPI) have no full-width rules, but they do
   have gutters: vertical bands of near-zero ink between columns. We project ink
   density onto each axis and split at the valleys.

Both paths return *edge positions in crop-local pixel coordinates*, plus a
confidence score so the UI can warn when the result is a guess.

Everything here is numpy-only. OpenCV would be the obvious tool, but the
operations we need — threshold, project, find runs, cluster — are a few lines
each and OpenCV is a ~50 MB dependency for a container that already ships
Tesseract and PyMuPDF.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# A pixel counts as ink below this luminance. Scanned drawings are usually
# bilevel already; this threshold also copes with anti-aliased CAD output.
INK_THRESHOLD = 160

# A row/column of the crop is a ruling line when at least this share of its
# pixels are ink. Real rules are continuous; text rows peak around 0.3-0.5.
LINE_COVERAGE = 0.55

# Adjacent ink rows within this many pixels are the same rule (a 2-3 px line
# plus its anti-aliasing halo).
LINE_MERGE_PX = 3

# A gutter must be at least this wide to be a column separator. Narrower gaps
# are inter-character spacing inside a cell.
MIN_GUTTER_PX = 6

# Ink density below this share counts as empty when looking for gutters.
GUTTER_INK = 0.02

# Cells narrower or shorter than this are almost certainly detection noise.
MIN_CELL_PX = 8

# Confidence reported when we had to fall back to whitespace projection.
WHITESPACE_CONFIDENCE = 0.45


@dataclass
class GridResult:
    """Row and column edges for one region, in crop-local pixels."""

    row_edges: list[int]
    col_edges: list[int]
    confidence: float
    method: str
    warnings: list[str] = field(default_factory=list)

    @property
    def rows(self) -> int:
        return max(0, len(self.row_edges) - 1)

    @property
    def cols(self) -> int:
        return max(0, len(self.col_edges) - 1)

    def to_dict(self) -> dict:
        return {
            "row_edges": self.row_edges,
            "col_edges": self.col_edges,
            "rows": self.rows,
            "cols": self.cols,
            "confidence": round(self.confidence, 3),
            "method": self.method,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# Image preparation
# ---------------------------------------------------------------------------


def to_ink_mask(image) -> np.ndarray:
    """Convert a PIL image to a boolean ink mask (True = ink).

    Handles RGB, RGBA, L, and 1-bit images. Alpha is composited over white so a
    transparent PNG crop does not read as solid ink.
    """
    from PIL import Image

    if image.mode == "RGBA":
        background = Image.new("RGBA", image.size, (255, 255, 255, 255))
        image = Image.alpha_composite(background, image)
    if image.mode not in ("L", "RGB"):
        image = image.convert("RGB")
    if image.mode == "RGB":
        image = image.convert("L")

    grey = np.asarray(image, dtype=np.uint8)
    return grey < INK_THRESHOLD


# ---------------------------------------------------------------------------
# Ruling-line detection
# ---------------------------------------------------------------------------


def _runs(flags: np.ndarray) -> list[tuple[int, int]]:
    """Return [start, end) index pairs for every run of True in a 1-D array."""
    if flags.size == 0:
        return []
    padded = np.concatenate(([False], flags.astype(bool), [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return [(int(edges[i]), int(edges[i + 1])) for i in range(0, len(edges), 2)]


def _merge_runs(runs: list[tuple[int, int]], gap: int) -> list[tuple[int, int]]:
    """Merge runs separated by fewer than `gap` pixels."""
    if not runs:
        return []
    merged = [list(runs[0])]
    for start, end in runs[1:]:
        if start - merged[-1][1] <= gap:
            merged[-1][1] = end
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def _line_positions(mask: np.ndarray, axis: int) -> list[int]:
    """Find ruling lines along one axis.

    `axis=0` projects down the rows (finds horizontal rules, i.e. row edges);
    `axis=1` projects across the columns (finds vertical rules, i.e. column
    edges). Returns the centre pixel of each detected rule.
    """
    # Fraction of ink along the perpendicular direction, per position.
    coverage = mask.mean(axis=axis)
    candidates = coverage >= LINE_COVERAGE
    runs = _merge_runs(_runs(candidates), LINE_MERGE_PX)
    return [int((start + end - 1) // 2) for start, end in runs]


# ---------------------------------------------------------------------------
# Whitespace projection
# ---------------------------------------------------------------------------


def _gutter_positions(mask: np.ndarray, axis: int) -> list[int]:
    """Find column/row separators as the centres of empty bands.

    Used when there are no ruling lines. A gutter is a run of positions whose
    ink density is essentially zero and which is wide enough not to be the space
    between two characters. Bands hugging the crop border are margins, not
    separators, so they are dropped — otherwise a table drawn with a wide left
    margin would gain a phantom first column.
    """
    density = mask.mean(axis=axis)
    empty = density <= GUTTER_INK
    runs = _merge_runs(_runs(empty), 1)
    extent = mask.shape[1] if axis == 0 else mask.shape[0]
    gutters = [
        int((start + end - 1) // 2)
        for start, end in runs
        if (end - start) >= MIN_GUTTER_PX
        # Drop margin bands: anything touching either border is not a
        # separator between two cells.
        and start > 0
        and end < extent
    ]
    return gutters


def _edges_from_gutters(gutters: list[int], extent: int) -> list[int]:
    """Turn gutter centres into cell boundaries.

    A gutter at x means the boundary sits at x; the region's own outer edges
    become the first and last boundary. Gutters hugging the border are dropped
    because they are the region's margin, not a separator.
    """
    inner = [g for g in gutters if MIN_CELL_PX <= g <= extent - MIN_CELL_PX]
    return [0, *inner, extent]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _dedupe_edges(
    edges: list[int],
    extent: int,
    *,
    margin_ink_start: float | None = None,
    margin_ink_end: float | None = None,
) -> list[int]:
    """Sort, clamp, and drop edges that would produce a degenerate cell.

    A gap between the crop border and the first/last detected edge is only a
    real cell when it contains ink. An empty margin band (the user drew the
    region loosely around the table) is dropped, so the outermost detected
    rules become the table borders and no phantom columns appear.
    """
    cleaned: list[int] = []
    for edge in sorted({int(e) for e in edges}):
        edge = max(0, min(extent, edge))
        if not cleaned or edge - cleaned[-1] >= MIN_CELL_PX:
            cleaned.append(edge)
    if not cleaned:
        return [0, extent]

    # A gap between the crop border and the outermost detected edge is a real
    # cell only when the band holds ink. An empty band is margin: the
    # outermost detected rule IS the table border, so it is kept as-is and the
    # crop bound is not appended (appending it would create a phantom column).
    if cleaned[-1] < extent - MIN_CELL_PX:
        if margin_ink_end is not None and margin_ink_end > GUTTER_INK:
            cleaned.append(extent)
    if cleaned[0] > MIN_CELL_PX:
        if margin_ink_start is not None and margin_ink_start > GUTTER_INK:
            cleaned.insert(0, 0)
    return cleaned


def _band_ink(mask: np.ndarray, axis: int, start: int, end: int) -> float:
    """Mean ink density of the band [start, end) along one axis."""
    if axis == 0:
        band = mask[:, start:end]
    else:
        band = mask[start:end, :]
    return float(band.mean()) if band.size else 0.0


def detect_grid(image, *, manual_rows: list[int] | None = None,
                manual_cols: list[int] | None = None) -> GridResult:
    """Detect the cell grid of a cropped table region.

    `manual_rows` / `manual_cols` are crop-local pixel positions the user has
    dragged in the editor. When supplied they replace the detected edges on that
    axis entirely — the user's intent always wins over the heuristic.
    """
    mask = to_ink_mask(image)
    height, width = mask.shape
    warnings: list[str] = []

    if height < MIN_CELL_PX or width < MIN_CELL_PX:
        return GridResult(
            row_edges=[0, height],
            col_edges=[0, width],
            confidence=0.0,
            method="degenerate",
            warnings=["Region is too small to contain a table."],
        )

    # --- rows ---------------------------------------------------------
    if manual_rows:
        row_edges = _dedupe_edges(list(manual_rows), height)
        row_method = "manual"
    else:
        detected = _line_positions(mask, axis=1)
        if len(detected) >= 2:
            row_edges = _dedupe_edges(
                detected,
                height,
                margin_ink_start=_band_ink(mask, 1, 0, detected[0]),
                # Start past the line itself: the detected centre sits on the
                # rule, and the band must measure only what lies beyond it.
                margin_ink_end=_band_ink(mask, 1, detected[-1] + LINE_MERGE_PX + 1, height),
            )
            row_method = "lines"
        else:
            row_edges = _edges_from_gutters(_gutter_positions(mask, axis=1), height)
            row_method = "whitespace"

    # --- columns ------------------------------------------------------
    if manual_cols:
        col_edges = _dedupe_edges(list(manual_cols), width)
        col_method = "manual"
    else:
        detected = _line_positions(mask, axis=0)
        if len(detected) >= 2:
            col_edges = _dedupe_edges(
                detected,
                width,
                margin_ink_start=_band_ink(mask, 0, 0, detected[0]),
                margin_ink_end=_band_ink(mask, 0, detected[-1] + LINE_MERGE_PX + 1, width),
            )
            col_method = "lines"
        else:
            col_edges = _edges_from_gutters(_gutter_positions(mask, axis=0), width)
            col_method = "whitespace"

    # --- confidence ---------------------------------------------------
    # Both axes from ruling lines is the trustworthy case. One axis from
    # whitespace is a reasonable guess. Both from whitespace is a guess we
    # should tell the user about.
    methods = {row_method, col_method}
    if methods == {"lines"}:
        confidence = 0.95
    elif methods == {"manual"}:
        confidence = 1.0
    elif "whitespace" in methods and "lines" in methods:
        confidence = 0.7
    elif methods == {"whitespace"}:
        confidence = WHITESPACE_CONFIDENCE
    else:
        confidence = 0.85  # one axis manual, one detected

    if row_method == "whitespace" or col_method == "whitespace":
        warnings.append(
            "No ruling lines found on one axis; edges were inferred from "
            "whitespace. Drag the guides to correct them."
        )
    rows = max(0, len(row_edges) - 1)
    cols = max(0, len(col_edges) - 1)
    if rows == 0 or cols == 0:
        warnings.append("Grid detection produced no cells.")

    return GridResult(
        row_edges=row_edges,
        col_edges=col_edges,
        confidence=confidence,
        method=f"rows:{row_method},cols:{col_method}",
        warnings=warnings,
    )


def cells_from_edges(
    row_edges: list[int], col_edges: list[int]
) -> list[tuple[int, int, tuple[int, int, int, int]]]:
    """Enumerate (row, col, bbox) for every cell in the grid.

    bbox is (x0, y0, x1, y1) in crop-local pixels.
    """
    cells: list[tuple[int, int, tuple[int, int, int, int]]] = []
    for r in range(len(row_edges) - 1):
        for c in range(len(col_edges) - 1):
            cells.append(
                (
                    r,
                    c,
                    (
                        col_edges[c],
                        row_edges[r],
                        col_edges[c + 1],
                        row_edges[r + 1],
                    ),
                )
            )
    return cells


def ink_ratio(image) -> float:
    """Share of pixels that are ink. Used to decide whether a cell is empty."""
    mask = to_ink_mask(image)
    if mask.size == 0:
        return 0.0
    return float(mask.mean())
