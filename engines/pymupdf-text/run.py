"""PyMuPDF text-layer extraction."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "pymupdf-text"


def handler(request: dict) -> EngineResponse:
    import pymupdf

    pdf_path = request["pdf_path"]
    pages: list[PageResult] = []

    with pymupdf.open(pdf_path) as doc:
        for index in range(doc.page_count):
            page = doc.load_page(index)
            text = page.get_text("text") or ""
            pages.append(PageResult(page=index + 1, text=text))

    return EngineResponse(
        ok=True,
        engine_id=ENGINE_ID,
        pages=pages,
        meta={"version": pymupdf.__doc__.split()[1] if pymupdf.__doc__ else "unknown"},
    )


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
