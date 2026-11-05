"""Anthropic Claude vision - general VLM transcription baseline."""

from __future__ import annotations

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "claude-vision"
ENDPOINT = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-5"

PROMPT = (
    "Transcribe all text in this engineering drawing verbatim as Markdown. "
    "Include dimension callouts, part numbers, and tables. Do not describe the "
    "image and do not invent text."
)


def handler(request: dict) -> EngineResponse:
    import httpx

    api_key = request["credentials"].get("anthropic_key")
    if not api_key:
        return EngineResponse(ok=False, engine_id=ENGINE_ID, error="Missing ANTHROPIC_KEY")

    pages: list[PageResult] = []
    with httpx.Client(timeout=150) as client:
        for index, image_path in enumerate(request["page_images"], start=1):
            encoded = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
            response = client.post(
                ENDPOINT,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": MODEL,
                    "max_tokens": 8192,
                    "temperature": 0,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": encoded,
                                    },
                                },
                                {"type": "text", "text": PROMPT},
                            ],
                        }
                    ],
                },
            )
            if response.status_code != 200:
                return EngineResponse(
                    ok=False,
                    engine_id=ENGINE_ID,
                    error=f"HTTP {response.status_code}: {response.text[:300]}",
                )
            payload = response.json()
            text = "".join(
                block.get("text", "")
                for block in payload.get("content", [])
                if block.get("type") == "text"
            )
            pages.append(PageResult(page=index, markdown=text))

    return EngineResponse(ok=True, engine_id=ENGINE_ID, pages=pages, meta={"model": MODEL})


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
