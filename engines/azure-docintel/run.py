"""Azure Document Intelligence - prebuilt-read and prebuilt-layout."""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "azure-docintel"
API_VERSION = "2024-11-30"


def handler(request: dict) -> EngineResponse:
    import httpx

    credentials = request["credentials"]
    endpoint = credentials.get("azure_docintel_endpoint")
    key = credentials.get("azure_docintel_key")
    if not endpoint or not key:
        return EngineResponse(
            ok=False,
            engine_id=ENGINE_ID,
            error="Missing AZURE_DOCINTEL_ENDPOINT or AZURE_DOCINTEL_KEY",
        )

    model = request.get("options", {}).get("model", "prebuilt-read")
    base = endpoint.rstrip("/")
    headers = {"Ocp-Apim-Subscription-Key": key}

    with httpx.Client(timeout=120) as client:
        with open(request["pdf_path"], "rb") as handle:
            submit = client.post(
                f"{base}/documentintelligence/documentModels/{model}:analyze",
                params={"api-version": API_VERSION, "_overload": "analyzeDocument"},
                headers={**headers, "Content-Type": "application/pdf"},
                content=handle.read(),
            )
        if submit.status_code not in (200, 202):
            return EngineResponse(
                ok=False,
                engine_id=ENGINE_ID,
                error=f"submit HTTP {submit.status_code}: {submit.text[:300]}",
            )

        operation = submit.headers.get("operation-location")
        if not operation:
            return EngineResponse(
                ok=False, engine_id=ENGINE_ID, error="No operation-location header"
            )

        payload = {}
        for _ in range(60):
            poll = client.get(operation, headers=headers)
            payload = poll.json()
            status = payload.get("status")
            if status == "succeeded":
                break
            if status == "failed":
                return EngineResponse(
                    ok=False,
                    engine_id=ENGINE_ID,
                    error=str(payload.get("error"))[:300],
                )
            time.sleep(2)
        else:
            return EngineResponse(ok=False, engine_id=ENGINE_ID, error="Analysis timed out")

    result = payload.get("analyzeResult") or {}
    by_page: dict[int, list[str]] = {}
    for paragraph in result.get("paragraphs", []):
        for region in paragraph.get("boundingRegions", []):
            page_number = int(region.get("pageNumber", 1))
            by_page.setdefault(page_number, []).append(paragraph.get("content", ""))

    pages: list[PageResult] = []
    for index in range(1, int(request.get("page_count") or 1) + 1):
        pages.append(
            PageResult(page=index, text="\n".join(by_page.get(index, [])))
        )

    return EngineResponse(
        ok=True,
        engine_id=ENGINE_ID,
        pages=pages,
        meta={"model": model, "tables": len(result.get("tables", []))},
    )


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
