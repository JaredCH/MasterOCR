"""Datalab API (Chandra 2) - the accuracy ceiling of the roster."""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "datalab-chandra"
BASE = "https://www.datalab.to/api/v1"


def handler(request: dict) -> EngineResponse:
    import httpx

    api_key = request["credentials"].get("datalab_key")
    if not api_key:
        return EngineResponse(ok=False, engine_id=ENGINE_ID, error="Missing DATALAB_KEY")

    headers = {"X-Api-Key": api_key}

    with httpx.Client(timeout=150) as client:
        with open(request["pdf_path"], "rb") as handle:
            submit = client.post(
                f"{BASE}/marker",
                headers=headers,
                files={"file": ("input.pdf", handle, "application/pdf")},
                data={"output_format": "markdown", "force_ocr": "true"},
            )
        if submit.status_code != 200:
            return EngineResponse(
                ok=False,
                engine_id=ENGINE_ID,
                error=f"submit HTTP {submit.status_code}: {submit.text[:300]}",
            )

        payload = submit.json()
        check_url = payload.get("request_check_url")
        if not check_url:
            return EngineResponse(
                ok=False, engine_id=ENGINE_ID, error="No request_check_url returned"
            )

        for _ in range(90):
            status = client.get(check_url, headers=headers).json()
            if status.get("status") == "complete":
                break
            if status.get("status") == "failed":
                return EngineResponse(
                    ok=False, engine_id=ENGINE_ID, error=str(status)[:300]
                )
            time.sleep(2)
        else:
            return EngineResponse(ok=False, engine_id=ENGINE_ID, error="Conversion timed out")

    markdown = status.get("markdown") or ""
    return EngineResponse(
        ok=True,
        engine_id=ENGINE_ID,
        pages=[PageResult(page=1, markdown=markdown)],
        meta={"pages": status.get("page_count")},
    )


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
