"""MMOCR - modular detector/recognizer zoo."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "mmocr"


def handler(request: dict) -> EngineResponse:
    from mmocr.apis import MMOCRInferencer

    inferencer = MMOCRInferencer(det="dbnetpp", rec="svtr-small", device="cpu")

    pages: list[PageResult] = []
    for index, image_path in enumerate(request["page_images"], start=1):
        result = inferencer(image_path, return_datasamples=False)
        predictions = result.get("predictions") or [{}]
        first = predictions[0] if predictions else {}

        texts = first.get("rec_texts") or []
        scores = first.get("rec_scores") or []
        pages.append(
            PageResult(
                page=index,
                text="\n".join(texts),
                confidence=sum(scores) / len(scores) if scores else None,
            )
        )

    return EngineResponse(ok=True, engine_id=ENGINE_ID, pages=pages)


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
