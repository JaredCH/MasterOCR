"""Tesseract OCR with a configurable page-segmentation mode.

PSM 3  = fully automatic (paragraph-oriented)
PSM 11 = sparse text (best for scattered drawing labels)
PSM 12 = sparse text with orientation detection
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "tesseract"
DEFAULT_PSM = 3


def handler(request: dict) -> EngineResponse:
    import pytesseract
    from PIL import Image

    psm = int(request.get("options", {}).get("psm", DEFAULT_PSM))
    config = f"--oem 3 --psm {psm}"

    pages: list[PageResult] = []
    for index, image_path in enumerate(request["page_images"], start=1):
        with Image.open(image_path) as image:
            text = pytesseract.image_to_string(image, lang="eng", config=config)
            # Per-word confidences let us report a mean confidence per page.
            data = pytesseract.image_to_data(
                image, lang="eng", config=config, output_type=pytesseract.Output.DICT
            )
        confidences = [
            float(value)
            for value in data.get("conf", [])
            if str(value).lstrip("-").replace(".", "", 1).isdigit() and float(value) >= 0
        ]
        mean_conf = (sum(confidences) / len(confidences) / 100.0) if confidences else None
        pages.append(PageResult(page=index, text=text, confidence=mean_conf))

    return EngineResponse(
        ok=True,
        engine_id=ENGINE_ID,
        pages=pages,
        meta={"psm": psm, "version": str(pytesseract.get_tesseract_version())},
    )


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
