"""Google Cloud Vision - DOCUMENT_TEXT_DETECTION."""

from __future__ import annotations

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "google-vision"
ENDPOINT = "https://vision.googleapis.com/v1/images:annotate"


def handler(request: dict) -> EngineResponse:
    import httpx

    api_key = request["credentials"].get("google_vision_key")
    if not api_key:
        return EngineResponse(ok=False, engine_id=ENGINE_ID, error="Missing GOOGLE_VISION_KEY")

    pages: list[PageResult] = []
    with httpx.Client(timeout=90) as client:
        for index, image_path in enumerate(request["page_images"], start=1):
            encoded = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
            response = client.post(
                ENDPOINT,
                params={"key": api_key},
                json={
                    "requests": [
                        {
                            "image": {"content": encoded},
                            "features": [
                                {"type": "DOCUMENT_TEXT_DETECTION", "maxResults": 1}
                            ],
                        }
                    ]
                },
            )
            if response.status_code != 200:
                return EngineResponse(
                    ok=False,
                    engine_id=ENGINE_ID,
                    error=f"HTTP {response.status_code}: {response.text[:300]}",
                )

            payload = response.json()
            result = (payload.get("responses") or [{}])[0]
            if "error" in result:
                return EngineResponse(
                    ok=False,
                    engine_id=ENGINE_ID,
                    error=str(result["error"].get("message"))[:300],
                )

            annotation = result.get("fullTextAnnotation") or {}
            text = annotation.get("text") or ""
            blocks = []
            for page in annotation.get("pages", []):
                for block in page.get("blocks", []):
                    blocks.append(
                        {
                            "type": "block",
                            "text": "".join(
                                "".join(
                                    symbol.get("text", "")
                                    for symbol in word.get("symbols", [])
                                )
                                for paragraph in block.get("paragraphs", [])
                                for word in paragraph.get("words", [])
                            ),
                            "confidence": block.get("confidence"),
                        }
                    )
            pages.append(PageResult(page=index, text=text, blocks=blocks))

    return EngineResponse(ok=True, engine_id=ENGINE_ID, pages=pages)


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
