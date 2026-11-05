"""Unstructured hi_res partition - element-level document structure."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "unstructured"


def handler(request: dict) -> EngineResponse:
    from unstructured.partition.pdf import partition_pdf

    elements = partition_pdf(
        filename=request["pdf_path"],
        strategy="hi_res",
        infer_table_structure=True,
    )

    by_page: dict[int, list] = {}
    for element in elements:
        page_number = int(getattr(element.metadata, "page_number", 1) or 1)
        by_page.setdefault(page_number, []).append(element)

    pages: list[PageResult] = []
    for page_number in sorted(by_page):
        page_elements = by_page[page_number]
        blocks = [
            {
                "type": getattr(element, "category", "Unknown"),
                "text": str(element),
            }
            for element in page_elements
        ]
        pages.append(
            PageResult(
                page=page_number,
                text="\n\n".join(block["text"] for block in blocks),
                blocks=blocks,
            )
        )

    return EngineResponse(
        ok=True,
        engine_id=ENGINE_ID,
        pages=pages,
        meta={"element_count": len(elements)},
    )


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
