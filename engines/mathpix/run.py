"""Mathpix - best-in-class math/LaTeX OCR."""

from __future__ import annotations

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "mathpix"
ENDPOINT = "https://api.mathpix.com/v3/pdf"


def handler(request: dict) -> EngineResponse:
    import httpx

    credentials = request["credentials"]
    app_id = credentials.get("mathpix_app_id")
    app_key = credentials.get("mathpix_app_key")
    if not app_id or not app_key:
        return EngineResponse(
            ok=False, engine_id=ENGINE_ID, error="Missing MATHPIX_APP_ID or MATHPIX_APP_KEY"
        )

    encoded = base64.b64encode(Path(request["pdf_path"]).read_bytes()).decode("ascii")

    with httpx.Client(timeout=150) as client:
        response = client.post(
            ENDPOINT,
            headers={
                "app_id": app_id,
                "app_key": app_key,
                "Content-Type": "application/json",
            },
            json={
                "src": f"data:application/pdf;base64,{encoded}",
                "options": {"conversion_formats": {"md": True}},
            },
        )

    if response.status_code != 200:
        return EngineResponse(
            ok=False,
            engine_id=ENGINE_ID,
            error=f"HTTP {response.status_code}: {response.text[:300]}",
        )

    payload = response.json()
    markdown = payload.get("markdown") or payload.get("text") or ""
    return EngineResponse(
        ok=True,
        engine_id=ENGINE_ID,
        pages=[PageResult(page=1, markdown=markdown)],
    )


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
