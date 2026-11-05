"""GNU Ocrad - legacy engine, included as a historical control."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "ocrad"


def handler(request: dict) -> EngineResponse:
    pages: list[PageResult] = []
    for index, image_path in enumerate(request["page_images"], start=1):
        result = subprocess.run(
            ["ocrad", "--format=utf8", image_path],
            capture_output=True,
            text=True,
            timeout=110,
            check=False,
        )
        if result.returncode != 0:
            return EngineResponse(
                ok=False,
                engine_id=ENGINE_ID,
                error=f"ocrad failed: {result.stderr.strip()[:300]}",
            )
        pages.append(PageResult(page=index, text=result.stdout))

    return EngineResponse(ok=True, engine_id=ENGINE_ID, pages=pages)


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
