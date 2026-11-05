"""Nougat - academic-PDF specialist with LaTeX math output."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "nougat"


def handler(request: dict) -> EngineResponse:
    from nougat import NougatModel
    from nougat.utils.dataset import ImageDataset
    from nougat.utils.device import move_to_device
    from nougat.postprocessing import markdown_compatible
    from PIL import Image
    import torch

    model = NougatModel.from_pretrained("facebook/nougat-base")
    model = move_to_device(model, bf16=False, cuda=False)
    model.eval()

    pages: list[PageResult] = []
    for index, image_path in enumerate(request["page_images"], start=1):
        with Image.open(image_path) as image:
            image = image.convert("RGB")
            tensor = model.encoder.prepare_input(image)
            with torch.no_grad():
                output = model.inference(image_tensors=[tensor])
        text = markdown_compatible(output["predictions"][0])
        pages.append(PageResult(page=index, markdown=text))

    return EngineResponse(ok=True, engine_id=ENGINE_ID, pages=pages)


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
