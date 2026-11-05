"""PaddleOCR PP-StructureV3 - layout, tables, and formulas."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "paddleocr-structure"


def handler(request: dict) -> EngineResponse:
    from paddleocr import PPStructure

    engine = PPStructure(show_log=False, layout=True, table=True, ocr=True)
    pages: list[PageResult] = []

    for index, image_path in enumerate(request["page_images"], start=1):
        regions = engine(image_path)
        markdown_parts = []
        blocks = []
        for region in regions:
            region_type = region.get("type", "text")
            if region_type == "table":
                html = region.get("res", {}).get("html", "")
                markdown_parts.append(html)
                blocks.append({"type": "table", "text": html})
            else:
                lines = region.get("res") or []
                text = "\n".join(
                    line.get("text", "") for line in lines if isinstance(line, dict)
                )
                if text:
                    markdown_parts.append(text)
                    blocks.append({"type": region_type, "text": text})

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
