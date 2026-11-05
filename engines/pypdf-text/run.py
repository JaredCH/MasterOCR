"""pypdf text-layer extraction (pure Python control)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "pypdf-text"


def handler(request: dict) -> EngineResponse:
    from pypdf import PdfReader

    reader = PdfReader(request["pdf_path"])
    pages = [
        PageResult(page=index, text=page.extract_text() or "")
        for index, page in enumerate(reader.pages, start=1)
    ]
    return EngineResponse(ok=True, engine_id=ENGINE_ID, pages=pages)


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
