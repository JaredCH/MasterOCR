"""Docling - layout-aware document conversion to Markdown."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "docling"


def handler(request: dict) -> EngineResponse:
    from docling.document_converter import DocumentConverter

    converter = DocumentConverter()
    result = converter.convert(request["pdf_path"])
    document = result.document

    pages: list[PageResult] = []
    page_count = int(request.get("page_count") or 1)

    # Docling exports the whole document at once; per-page export keeps the
    # comparison aligned with the other engines.
    for page_number in range(1, page_count + 1):
        try:
            markdown = document.export_to_markdown(page_no=page_number)
        except Exception:  # noqa: BLE001 - page may not exist in the model
            markdown = ""
        pages.append(PageResult(page=page_number, markdown=markdown))

    if not any(page.markdown for page in pages):
        pages = [PageResult(page=1, markdown=document.export_to_markdown())]

    return EngineResponse(
        ok=True,
        engine_id=ENGINE_ID,
        pages=pages,
        meta={"tables": len(getattr(document, "tables", []) or [])},
    )


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
