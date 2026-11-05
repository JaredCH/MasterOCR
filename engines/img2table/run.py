"""img2table - table detection on rasterized page images."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "img2table"


def handler(request: dict) -> EngineResponse:
    from img2table.document import Image
    from img2table.ocr import TesseractOCR

    ocr = TesseractOCR(n_threads=1, lang="eng")
    pages: list[PageResult] = []

    for index, image_path in enumerate(request["page_images"], start=1):
        try:
            document = Image(src=image_path)
            extracted = document.extract_tables(ocr=ocr, implicit_rows=True)
        except Exception as exc:  # noqa: BLE001 - per-page failure is not fatal
            pages.append(PageResult(page=index, text="", blocks=[]))
            continue

        markdown_parts = []
        blocks = []
        for table in extracted:
            frame = table.df
            markdown_parts.append(frame.to_markdown(index=False))
            blocks.append(
                {
                    "type": "table",
                    "text": frame.to_csv(index=False),
                    "bbox": [
                        table.bbox.x1,
                        table.bbox.y1,
                        table.bbox.x2,
                        table.bbox.y2,
                    ]
                    if getattr(table, "bbox", None)
                    else None,
                }
            )

        pages.append(
            PageResult(
                page=index,
                markdown="\n\n".join(markdown_parts),
                blocks=blocks,
            )
        )

    return EngineResponse(ok=True, engine_id=ENGINE_ID, pages=pages)


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
