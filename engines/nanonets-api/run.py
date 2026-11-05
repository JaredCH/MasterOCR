"""Nanonets OCR API - hosted OCR-2 model with structured Markdown."""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "nanonets-api"
BASE = "https://app.nanonets.com/api/v2/OCR/Model"


def handler(request: dict) -> EngineResponse:
    import httpx

    api_key = request["credentials"].get("nanonets_key")
    if not api_key:
        return EngineResponse(ok=False, engine_id=ENGINE_ID, error="Missing NANONETS_KEY")

    auth = (api_key, "")

    with httpx.Client(timeout=150) as client:
        with open(request["pdf_path"], "rb") as handle:
            submit = client.post(
                f"{BASE}/ocr_full/",
                auth=auth,
                files={"file": ("input.pdf", handle, "application/pdf")},
            )
        if submit.status_code not in (200, 201):
            return EngineResponse(
                ok=False,
                engine_id=ENGINE_ID,
                error=f"submit HTTP {submit.status_code}: {submit.text[:300]}",
            )

        payload = submit.json()
        pages = []
        for index, page in enumerate(payload.get("result", []), start=1):
            prediction = page.get("prediction") or []
            text = "\n".join(
                item.get("ocr_text", "")
                for item in prediction
                if isinstance(item, dict)
            )
            pages.append(PageResult(page=index, text=text))

    return EngineResponse(ok=True, engine_id=ENGINE_ID, pages=pages)


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
