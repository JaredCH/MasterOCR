"""mutool draw -F txt (MuPDF CLI) text-layer extraction."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "mupdf-mutool"


def handler(request: dict) -> EngineResponse:
    pdf_path = request["pdf_path"]
    page_count = int(request.get("page_count") or 1)

    pages: list[PageResult] = []
    for page_number in range(1, page_count + 1):
        result = subprocess.run(
            ["mutool", "draw", "-F", "txt", "-o", "-", pdf_path, str(page_number)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if result.returncode != 0:
            return EngineResponse(
                ok=False,
                engine_id=ENGINE_ID,
                error=f"mutool failed: {result.stderr.strip()[:500]}",
            )
        pages.append(PageResult(page=page_number, text=result.stdout))

    return EngineResponse(ok=True, engine_id=ENGINE_ID, pages=pages)


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
