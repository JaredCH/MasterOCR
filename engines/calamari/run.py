"""Calamari OCR - line-based, fast on clean print."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "calamari"


def handler(request: dict) -> EngineResponse:
    from calamari_ocr.ocr import Predictor
    from calamari_ocr.ocr.dataset import FileData

    predictor = Predictor(
        checkpoint="default",
        text_postproc=None,
        silence_logger=True,
    )

    pages: list[PageResult] = []
    for index, image_path in enumerate(request["page_images"], start=1):
        data = FileData(image_path)
        results = list(predictor.predict([data]))
        text = "\n".join(
            "".join(sentence.text for sentence in sample.sentences)
            for sample in results
        )
        pages.append(PageResult(page=index, text=text))

    return EngineResponse(ok=True, engine_id=ENGINE_ID, pages=pages)


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
