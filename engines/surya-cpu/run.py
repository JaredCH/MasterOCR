"""Surya - layout, OCR, and tables in one model (CPU inference)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "surya-cpu"


def handler(request: dict) -> EngineResponse:
    from PIL import Image
    from surya.recognition import RecognitionPredictor
    from surya.detection import DetectionPredictor

    detector = DetectionPredictor()
    recognizer = RecognitionPredictor()

    pages: list[PageResult] = []
    for index, image_path in enumerate(request["page_images"], start=1):
        with Image.open(image_path) as image:
            image = image.convert("RGB")
            predictions = detector([image])
            results = recognizer([image], det_predictor=detector)

        lines = []
        blocks = []
        confidences = []
        for result in results:
            for line in getattr(result, "text_lines", []):
                text = getattr(line, "text", "")
                confidence = getattr(line, "confidence", None)
                if confidence is not None:
                    confidences.append(float(confidence))
                lines.append(text)
                blocks.append(
                    {
                        "type": "line",
                        "text": text,
                        "bbox": getattr(line, "bbox", None),
                        "confidence": confidence,
                    }
                )

        pages.append(
            PageResult(
                page=index,
                text="\n".join(lines),
                blocks=blocks,
                confidence=sum(confidences) / len(confidences) if confidences else None,
            )
        )

    return EngineResponse(ok=True, engine_id=ENGINE_ID, pages=pages)


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
