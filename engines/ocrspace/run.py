"""OCR.space Engine 2 and Engine 3.

The free tier caps PDFs at 3 pages and 1 MB, so we send page images one at a
time rather than the whole PDF. That keeps every page comparable and avoids
silent truncation.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "ocrspace"
ENDPOINT = "https://api.ocr.space/parse/image"
MAX_BYTES = 1_000_000


def _encode(image_path: str) -> str:
    data = Path(image_path).read_bytes()
    if len(data) > MAX_BYTES:
        # Downscale until it fits the free-tier cap.
        from PIL import Image
        import io

        with Image.open(image_path) as image:
            for scale in (0.75, 0.5, 0.35, 0.25):
                buffer = io.BytesIO()
                resized = image.resize(
                    (int(image.width * scale), int(image.height * scale))
                )
                resized.save(buffer, format="JPEG", quality=80)
                if buffer.tell() <= MAX_BYTES:
                    data = buffer.getvalue()
                    break
    return "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")


def handler(request: dict) -> EngineResponse:
    import httpx

    api_key = request["credentials"].get("ocrspace_key")
    if not api_key:
        return EngineResponse(ok=False, engine_id=ENGINE_ID, error="Missing OCRSPACE_KEY")

    engine_number = int(request.get("options", {}).get("engine", 2))
    pages: list[PageResult] = []

    with httpx.Client(timeout=90) as client:
        for index, image_path in enumerate(request["page_images"], start=1):
            response = client.post(
                ENDPOINT,
                headers={"apikey": api_key},
                data={
                    "base64Image": _encode(image_path),
                    "OCREngine": str(engine_number),
                    "language": "auto",
                    "isOverlayRequired": "false",
                    "scale": "true",
                    "isTable": "true" if engine_number == 3 else "false",
                },
            )
            if response.status_code != 200:
                return EngineResponse(
                    ok=False,
                    engine_id=ENGINE_ID,
                    error=f"HTTP {response.status_code}: {response.text[:300]}",
                )

            payload = response.json()
            if payload.get("IsErroredOnProcessing"):
                return EngineResponse(
                    ok=False,
                    engine_id=ENGINE_ID,
                    error=str(payload.get("ErrorMessage"))[:300],
                )

            parsed = payload.get("ParsedResults") or []
            text = "\n".join(item.get("ParsedText") or "" for item in parsed)
            pages.append(PageResult(page=index, text=text))

    return EngineResponse(
        ok=True, engine_id=ENGINE_ID, pages=pages, meta={"engine": engine_number}
    )


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
