"""PDF rasterization and born-digital detection.

The test corpus is mixed: some PDFs are CAD exports with a real text layer,
others are scans. Text-layer engines are meaningless on a scan, and OCR engines
are redundant on a clean digital export — so we classify every page first and
record that classification alongside the results.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pymupdf

PageClass = Literal["born_digital", "raster", "vector", "mixed", "empty"]

# A page needs at least this many characters of extractable text before we
# treat it as born-digital. Below this, the text layer is usually just a
# watermark or a stray stamp.
MIN_TEXT_CHARS = 40

# CAD plots often convert text to vector outlines, so a page can be full of
# geometry with no text layer and no embedded image. Above this many drawing
# paths we treat the page as a vector plot that must be rasterized.
MIN_VECTOR_PATHS = 50


@dataclass
class PageInfo:
    number: int
    width_pt: float
    height_pt: float
    text_chars: int
    image_count: int
    vector_paths: int
    classification: PageClass
    image_path: Path | None = None


@dataclass
class DocumentInfo:
    page_count: int
    pages: list[PageInfo]
    title: str | None = None
    producer: str | None = None

    @property
    def classification(self) -> PageClass:
        kinds = {page.classification for page in self.pages}
        if len(kinds) == 1:
            return next(iter(kinds))
        return "mixed"


def _classify(text_chars: int, image_count: int, vector_paths: int) -> PageClass:
    if text_chars >= MIN_TEXT_CHARS:
        return "born_digital"
    if image_count > 0:
        return "raster"
    if vector_paths >= MIN_VECTOR_PATHS:
        # Vector CAD plot: text was converted to outlines, so only OCR on a
        # rasterized render can recover it.
        return "vector"
    return "empty"


def inspect(pdf_path: Path, *, dpi: int, output_dir: Path, max_pages: int) -> DocumentInfo:
    """Classify every page and render page images for the OCR engines."""
    output_dir.mkdir(parents=True, exist_ok=True)
    pages: list[PageInfo] = []

    with pymupdf.open(pdf_path) as doc:
        metadata = doc.metadata or {}
        limit = min(doc.page_count, max_pages)

        for index in range(limit):
            page = doc.load_page(index)
            text = page.get_text("text") or ""
            image_count = len(page.get_images(full=True))
            vector_paths = len(page.get_drawings())
            classification = _classify(
                len(text.strip()), image_count, vector_paths
            )

            image_path = output_dir / f"p{index + 1:04d}.png"
            # 300 DPI is the sweet spot for engineering drawings: small
            # dimension callouts stay legible without exploding file size.
            pixmap = page.get_pixmap(dpi=dpi, alpha=False)
            pixmap.save(image_path)

            pages.append(
                PageInfo(
                    number=index + 1,
                    width_pt=page.rect.width,
                    height_pt=page.rect.height,
                    text_chars=len(text.strip()),
                    image_count=image_count,
                    vector_paths=vector_paths,
                    classification=classification,
                    image_path=image_path,
                )
            )

    return DocumentInfo(
        page_count=len(pages),
        pages=pages,
        title=metadata.get("title") or None,
        producer=metadata.get("producer") or None,
    )


def extract_text_layer(pdf_path: Path, *, max_pages: int) -> list[str]:
    """Raw text layer per page, used as the reference for born-digital docs."""
    with pymupdf.open(pdf_path) as doc:
        limit = min(doc.page_count, max_pages)
        return [doc.load_page(index).get_text("text") or "" for index in range(limit)]
