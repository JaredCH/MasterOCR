"""Kraken - historical-document OCR, strong on degraded scans."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "kraken"


def handler(request: dict) -> EngineResponse:
    from kraken import blla, rpred
    from kraken.lib import models
    from PIL import Image

    model = models.load_any("en_best.mlmodel")

    pages: list[PageResult] = []
    for index, image_path in enumerate(request["page_images"], start=1):
        with Image.open(image_path) as image:
            image = image.convert("L")
            segmentation = blla.segment(image)
            records = list(rpred.rpred(model, image, segmentation))

        lines = [record.prediction for record in records]
        pages.append(PageResult(page=index, text="\n".join(lines)))

    return EngineResponse(ok=True, engine_id=ENGINE_ID, pages=pages)


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
