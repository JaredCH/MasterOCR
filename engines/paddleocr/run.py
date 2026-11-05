"""PaddleOCR PP-OCRv5 - strong on dense small text."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "paddleocr"


def handler(request: dict) -> EngineResponse:
    from paddleocr import PaddleOCR

    ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
    pages: list[PageResult] = []

    for index, image_path in enumerate(request["page_images"], start=1):
        result = ocr.ocr(image_path, cls=True)
        lines = result[0] if result and result[0] else []

        blocks = []
        scores = []
        for box, (text, score) in lines:
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
