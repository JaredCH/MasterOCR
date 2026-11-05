"""Qwen3-VL via OpenRouter - open-weight VLM through a single API."""

from __future__ import annotations

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "openrouter-qwen3vl"
ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "qwen/qwen3-vl-235b-a22b-instruct"

PROMPT = (
    "Transcribe all text in this engineering drawing verbatim as Markdown. "
    "Include dimension callouts, part numbers, and table contents. Do not "
    "describe the image and do not invent text."
)


def handler(request: dict) -> EngineResponse:
    import httpx

    api_key = request["credentials"].get("openrouter_key")
    if not api_key:
        return EngineResponse(ok=False, engine_id=ENGINE_ID, error="Missing OPENROUTER_KEY")

    pages: list[PageResult] = []
    with httpx.Client(timeout=150) as client:
        for index, image_path in enumerate(request["page_images"], start=1):
            encoded = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
            response = client.post(
                ENDPOINT,
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": MODEL,
                    "temperature": 0,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": PROMPT},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/png;base64,{encoded}"
                                    },
                                },
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
            choices = payload.get("choices") or []
            text = (
                choices[0].get("message", {}).get("content", "") if choices else ""
            )
            pages.append(PageResult(page=index, markdown=text))

    return EngineResponse(ok=True, engine_id=ENGINE_ID, pages=pages, meta={"model": MODEL})


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
