"""MarkItDown - lightweight PDF to Markdown (text layer only, no OCR)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "markitdown"


def handler(request: dict) -> EngineResponse:
    from markitdown import MarkItDown

    converter = MarkItDown(enable_plugins=False)
    result = converter.convert_local(request["pdf_path"])
    markdown = result.markdown or ""

    # MarkItDown emits one document; split on its page markers when present.
    page_count = int(request.get("page_count") or 1)
    if page_count > 1 and "<!-- page " in markdown:
        chunks = markdown.split("<!-- page ")
        pages = [
            PageResult(page=index, markdown=chunk)
            for index, chunk in enumerate(chunks[1:], start=1)
        ]
    else:
        pages = [PageResult(page=1, markdown=markdown)]

    return EngineResponse(ok=True, engine_id=ENGINE_ID, pages=pages)


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
