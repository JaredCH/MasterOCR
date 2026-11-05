"""LlamaParse - agentic document parsing to Markdown."""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "llamaparse"
BASE = "https://api.cloud.llamaindex.ai/api/v1/parsing"


def handler(request: dict) -> EngineResponse:
    import httpx

    api_key = request["credentials"].get("llamaparse_key")
    if not api_key:
        return EngineResponse(ok=False, engine_id=ENGINE_ID, error="Missing LLAMAPARSE_KEY")

    headers = {"Authorization": f"Bearer {api_key}"}

    with httpx.Client(timeout=120) as client:
        with open(request["pdf_path"], "rb") as handle:
            upload = client.post(
                f"{BASE}/upload",
                headers=headers,
                files={"file": ("input.pdf", handle, "application/pdf")},
            )
        if upload.status_code not in (200, 201):
            return EngineResponse(
                ok=False,
                engine_id=ENGINE_ID,
                error=f"upload HTTP {upload.status_code}: {upload.text[:300]}",
            )
        job_id = upload.json().get("id")

        for _ in range(60):
            status = client.get(f"{BASE}/job/{job_id}", headers=headers).json()
            if status.get("status") == "SUCCESS":
                break
            if status.get("status") == "ERROR":
                return EngineResponse(
                    ok=False, engine_id=ENGINE_ID, error=str(status)[:300]
                )
            time.sleep(2)
        else:
            return EngineResponse(ok=False, engine_id=ENGINE_ID, error="Parse timed out")

        result = client.get(
            f"{BASE}/job/{job_id}/result/markdown", headers=headers
        )
        if result.status_code != 200:
            return EngineResponse(
                ok=False,
                engine_id=ENGINE_ID,
                error=f"result HTTP {result.status_code}: {result.text[:300]}",
            )
        markdown = result.json().get("markdown", "")

    return EngineResponse(
        ok=True,
        engine_id=ENGINE_ID,
        pages=[PageResult(page=1, markdown=markdown)],
    )


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
