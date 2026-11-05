"""pdfplumber text-layer extraction with word positions."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "pdfplumber-text"


def handler(request: dict) -> EngineResponse:
    import pdfplumber

    pages: list[PageResult] = []
    with pdfplumber.open(request["pdf_path"]) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            words = page.extract_words() or []
            blocks = [
                {
                    "type": "word",
                    "text": word["text"],
                    "bbox": [
                        round(word["x0"], 2),
                        round(word["top"], 2),
                        round(word["x1"], 2),
                        round(word["bottom"], 2),
                    ],
                }
                for word in words
            ]
            pages.append(PageResult(page=index, text=text, blocks=blocks))

    return EngineResponse(ok=True, engine_id=ENGINE_ID, pages=pages)


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
