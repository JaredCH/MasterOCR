"""TrOCR - transformer line recognizer paired with Tesseract line boxes."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "trocr"


def handler(request: dict) -> EngineResponse:
    import pytesseract
    from PIL import Image
    from transformers import TrOCRProcessor, VisionEncoderDecoderModel

    processor = TrOCRProcessor.from_pretrained("microsoft/trocr-base-printed")
    model = VisionEncoderDecoderModel.from_pretrained("microsoft/trocr-base-printed")

    pages: list[PageResult] = []
    for index, image_path in enumerate(request["page_images"], start=1):
        with Image.open(image_path) as image:
            image = image.convert("RGB")
            # Tesseract supplies the line boxes; TrOCR reads each crop.
            data = pytesseract.image_to_data(
                image, output_type=pytesseract.Output.DICT
            )
            lines = []
            for i, text in enumerate(data["text"]):
                if not text.strip():
                    continue
                x, y, w, h = (
                    data["left"][i],
                    data["top"][i],
                    data["width"][i],
                    data["height"][i],
                )
                if w < 8 or h < 8:
                    continue
                crop = image.crop((x, y, x + w, y + h))
                pixel_values = processor(crop, return_tensors="pt").pixel_values
                ids = model.generate(pixel_values, max_new_tokens=64)
                lines.append(processor.batch_decode(ids, skip_special_tokens=True)[0])

        pages.append(PageResult(page=index, text="\n".join(lines)))

    return EngineResponse(ok=True, engine_id=ENGINE_ID, pages=pages)


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
