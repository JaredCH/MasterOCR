"""Reducto - agentic document parsing with strong table handling."""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "reducto"
BASE = "https://platform.reducto.ai"


def handler(request: dict) -> EngineResponse:
    import httpx

    api_key = request["credentials"].get("reducto_key")
    if not api_key:
        return EngineResponse(ok=False, engine_id=ENGINE_ID, error="Missing REDUCTO_KEY")

    headers = {"Authorization": f"Bearer {api_key}"}

    with httpx.Client(timeout=150) as client:
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
        file_id = upload.json().get("file_id")

        parse = client.post(
            f"{BASE}/parse",
            headers=headers,
            json={"input": file_id, "enhance": {"agentic": []}},
        )
        if parse.status_code != 200:
            return EngineResponse(
                ok=False,
                engine_id=ENGINE_ID,
                error=f"parse HTTP {parse.status_code}: {parse.text[:300]}",
            )

        payload = parse.json()

    chunks = payload.get("result", {}).get("chunks", [])
    pages = [
        PageResult(page=index, markdown=chunk.get("content", ""))
        for index, chunk in enumerate(chunks, start=1)
    ]
    if not pages:
        pages = [PageResult(page=1, markdown="")]

    return EngineResponse(ok=True, engine_id=ENGINE_ID, pages=pages)


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
