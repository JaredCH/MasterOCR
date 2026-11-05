"""PyMuPDF4LLM - Markdown tuned for LLM ingestion (text layer only)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "pymupdf4llm"


def handler(request: dict) -> EngineResponse:
    import pymupdf4llm

    page_count = int(request.get("page_count") or 1)
    pages: list[PageResult] = []

    for page_number in range(page_count):
        try:
            markdown = pymupdf4llm.to_markdown(
                request["pdf_path"], pages=[page_number]
            )
        except Exception:  # noqa: BLE001 - empty page or unsupported content
            markdown = ""
        pages.append(PageResult(page=page_number + 1, markdown=markdown))

    return EngineResponse(ok=True, engine_id=ENGINE_ID, pages=pages)


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
