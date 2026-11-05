"""EasyOCR - CRAFT detector plus CRNN recognizer."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "easyocr"


def handler(request: dict) -> EngineResponse:
    import easyocr

    reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    pages: list[PageResult] = []

    for index, image_path in enumerate(request["page_images"], start=1):
        results = reader.readtext(image_path, detail=1, paragraph=False)
        blocks = []
        scores = []
        for box, text, score in results:
            scores.append(float(score))
            xs = [point[0] for point in box]
            ys = [point[1] for point in box]
            blocks.append(
                {
                    "type": "line",
                    "text": text,
                    "bbox": [min(xs), min(ys), max(xs), max(ys)],
                    "confidence": float(score),
                }
            )
        pages.append(
            PageResult(
                page=index,
                text="\n".join(block["text"] for block in blocks),
                blocks=blocks,
                confidence=sum(scores) / len(scores) if scores else None,
            )
        )

    return EngineResponse(ok=True, engine_id=ENGINE_ID, pages=pages)


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
