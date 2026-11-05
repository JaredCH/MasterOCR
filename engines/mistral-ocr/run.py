"""Mistral OCR - document-native OCR endpoint with Markdown output."""

from __future__ import annotations

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "mistral-ocr"
ENDPOINT = "https://api.mistral.ai/v1/ocr"
MODEL = "mistral-ocr-latest"


def handler(request: dict) -> EngineResponse:
    import httpx

    api_key = request["credentials"].get("mistral_key")
    if not api_key:
        return EngineResponse(ok=False, engine_id=ENGINE_ID, error="Missing MISTRAL_KEY")

    encoded = base64.b64encode(Path(request["pdf_path"]).read_bytes()).decode("ascii")

    with httpx.Client(timeout=150) as client:
        response = client.post(
            ENDPOINT,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": MODEL,
                "document": {
                    "type": "document_url",
                    "document_url": f"data:application/pdf;base64,{encoded}",
                },
                "include_image_base64": False,
            },
        )

    if response.status_code != 200:
        return EngineResponse(
            ok=False,
            engine_id=ENGINE_ID,
            error=f"HTTP {response.status_code}: {response.text[:300]}",
        )

    payload = response.json()
    pages = [
        PageResult(
            page=int(page.get("index", index)) + 1,
            markdown=page.get("markdown", ""),
        )
        for index, page in enumerate(payload.get("pages", []))
    ]

    return EngineResponse(ok=True, engine_id=ENGINE_ID, pages=pages, meta={"model": MODEL})


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
