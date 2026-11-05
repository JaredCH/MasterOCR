"""pdfminer.six text-layer extraction."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "pdfminer-text"


def handler(request: dict) -> EngineResponse:
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LTTextContainer

    pages: list[PageResult] = []
    for index, layout in enumerate(extract_pages(request["pdf_path"]), start=1):
        chunks = [
            element.get_text()
            for element in layout
            if isinstance(element, LTTextContainer)
        ]
        pages.append(PageResult(page=index, text="".join(chunks)))

    return EngineResponse(ok=True, engine_id=ENGINE_ID, pages=pages)


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
