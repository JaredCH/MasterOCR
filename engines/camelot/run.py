"""Camelot - table extraction (lattice first, stream as fallback)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "camelot"


def handler(request: dict) -> EngineResponse:
    import camelot

    pages: list[PageResult] = []
    page_count = int(request.get("page_count") or 1)

    for page_number in range(1, page_count + 1):
        tables = None
        for flavor in ("lattice", "stream"):
            try:
                found = camelot.read_pdf(
                    request["pdf_path"],
                    pages=str(page_number),
                    flavor=flavor,
                )
            except Exception:  # noqa: BLE001 - flavor may not apply to this page
                continue
            if len(found) > 0:
                tables = found
                break

        if not tables:
            pages.append(PageResult(page=page_number, text=""))
            continue

        markdown_parts = []
        blocks = []
        for table in tables:
            markdown_parts.append(table.df.to_markdown(index=False))
            blocks.append(
                {
                    "type": "table",
                    "text": table.df.to_csv(index=False),
                    "bbox": list(table.bbox) if hasattr(table, "bbox") else None,
                }
            )

        pages.append(
            PageResult(
                page=page_number,
                markdown="\n\n".join(markdown_parts),
                blocks=blocks,
            )
        )

    return EngineResponse(ok=True, engine_id=ENGINE_ID, pages=pages)


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
