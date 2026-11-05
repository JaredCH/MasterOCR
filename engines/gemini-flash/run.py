"""Gemini Flash vision - general VLM prompted to transcribe the page."""

from __future__ import annotations

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "gemini-flash"
MODEL = "gemini-2.5-flash"

PROMPT = (
    "Transcribe every piece of text visible in this engineering drawing exactly "
    "as it appears. Preserve dimension callouts, part numbers, revision blocks, "
    "and table contents. Output Markdown. Do not describe the drawing, do not "
    "summarise, and do not add any text that is not present in the image. If a "
    "region is illegible, write [illegible] rather than guessing."
)


def handler(request: dict) -> EngineResponse:
    import httpx

    api_key = request["credentials"].get("gemini_key")
    if not api_key:
        return EngineResponse(ok=False, engine_id=ENGINE_ID, error="Missing GEMINI_KEY")

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    )

    pages: list[PageResult] = []
    with httpx.Client(timeout=120) as client:
        for index, image_path in enumerate(request["page_images"], start=1):
            encoded = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
            response = client.post(
                url,
                headers={"x-goog-api-key": api_key},
                json={
                    "contents": [
                        {
                            "parts": [
                                {"text": PROMPT},
                                {
                                    "inline_data": {
                                        "mime_type": "image/png",
                                        "data": encoded,
                                    }
                                },
                            ]
                        }
                    ],
                    "generationConfig": {"temperature": 0.0},
                },
            )
            if response.status_code != 200:
                return EngineResponse(
                    ok=False,
                    engine_id=ENGINE_ID,
                    error=f"HTTP {response.status_code}: {response.text[:300]}",
                )

            payload = response.json()
            candidates = payload.get("candidates") or []
            if not candidates:
                pages.append(PageResult(page=index, markdown=""))
                continue
            parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join(part.get("text", "") for part in parts)
            pages.append(PageResult(page=index, markdown=text))

    return EngineResponse(ok=True, engine_id=ENGINE_ID, pages=pages, meta={"model": MODEL})


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
