"""Google Document AI - enterprise OCR processor."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "google-docai"


def handler(request: dict) -> EngineResponse:
    import httpx

    project = request["credentials"].get("google_docai_project")
    if not project:
        return EngineResponse(
            ok=False, engine_id=ENGINE_ID, error="Missing GOOGLE_DOCAI_PROJECT"
        )

    # Document AI requires OAuth2, not an API key. The caller supplies a
    # short-lived access token through the options bag.
    token = request.get("options", {}).get("access_token")
    processor = request.get("options", {}).get("processor_id")
    location = request.get("options", {}).get("location", "us")
    if not token or not processor:
        return EngineResponse(
            ok=False,
            engine_id=ENGINE_ID,
            error="Document AI needs options.access_token and options.processor_id",
        )

    import base64

    encoded = base64.b64encode(Path(request["pdf_path"]).read_bytes()).decode("ascii")
    url = (
        f"https://{location}-documentai.googleapis.com/v1/projects/{project}"
        f"/locations/{location}/processors/{processor}:process"
    )

    with httpx.Client(timeout=150) as client:
        response = client.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json={"rawDocument": {"content": encoded, "mimeType": "application/pdf"}},
        )

    if response.status_code != 200:
        return EngineResponse(
            ok=False,
            engine_id=ENGINE_ID,
            error=f"HTTP {response.status_code}: {response.text[:300]}",
        )

    payload = response.json()
    document = payload.get("document") or {}
    text = document.get("text") or ""
    return EngineResponse(
        ok=True,
        engine_id=ENGINE_ID,
        pages=[PageResult(page=1, text=text)],
        meta={"pages": len(document.get("pages", []))},
    )


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
