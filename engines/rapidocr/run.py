"""RapidOCR — PP-OCRv4 models running on ONNX Runtime (CPU)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "rapidocr"


def handler(request: dict) -> EngineResponse:
    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR()
    pages: list[PageResult] = []

    for index, image_path in enumerate(request["page_images"], start=1):
        result, _ = engine(image_path)
        if not result:
            pages.append(PageResult(page=index, text=""))
            continue

        blocks = []
        scores = []
        for box, text, score in result:
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
