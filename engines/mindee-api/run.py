"""Mindee OCR - generic OCR endpoint."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "mindee-api"
ENDPOINT = "https://api.mindee.net/v1/products/mindee/ocr/v1/predict"


def handler(request: dict) -> EngineResponse:
    import httpx

    api_key = request["credentials"].get("mindee_key")
    if not api_key:
        return EngineResponse(ok=False, engine_id=ENGINE_ID, error="Missing MINDEE_KEY")

    pages: list[PageResult] = []
    with httpx.Client(timeout=120) as client:
        for index, image_path in enumerate(request["page_images"], start=1):
            with open(image_path, "rb") as handle:
                response = client.post(
                    ENDPOINT,
                    headers={"Authorization": f"Token {api_key}"},
                    files={"document": ("page.png", handle, "image/png")},
                )
            if response.status_code not in (200, 201):
                return EngineResponse(
                    ok=False,
                    engine_id=ENGINE_ID,
                    error=f"HTTP {response.status_code}: {response.text[:300]}",
                )
            payload = response.json()
            document = payload.get("document") or {}
            inference = document.get("inference") or {}
            pages.append(
                PageResult(page=index, text=inference.get("pages", [{}])[0].get("raw_text", ""))
            )

    return EngineResponse(ok=True, engine_id=ENGINE_ID, pages=pages)


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
