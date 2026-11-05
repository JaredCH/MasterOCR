"""The JSON contract spoken between the API and every engine adapter.

Every adapter is a standalone script invoked as::

    python engines/<engine_id>/run.py

It reads one JSON object from stdin and writes one JSON object to stdout.
Nothing else may be written to stdout — diagnostics go to stderr, which the
runner captures separately. This keeps a chatty library (PaddleOCR, Docling)
from corrupting the result payload.

Request
-------
{
  "engine_id": "tesseract-psm11",
  "pdf_path": "/data/work/<job>/input.pdf",
  "page_images": ["/data/work/<job>/pages/p0001.png", ...],
  "page_count": 3,
  "dpi": 300,
  "options": {"psm": 11},
  "credentials": {"ocrspace_key": "..."}   # only the keys this engine needs
}

Response
--------
{
  "ok": true,
  "engine_id": "tesseract-psm11",
  "pages": [
    {
      "page": 1,
      "text": "raw text",
      "markdown": null,
      "html": null,
      "blocks": [{"type": "text", "text": "...", "bbox": [x0,y0,x1,y1]}],
      "confidence": 0.87
    }
  ],
  "meta": {"version": "5.5.4", "warnings": []},
  "error": null
}

On failure the adapter must still emit a well-formed response with
``ok: false`` and a human-readable ``error``. A non-zero exit code or
unparseable stdout is treated by the runner as a crash.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class PageResult:
    page: int
    text: str = ""
    markdown: str | None = None
    html: str | None = None
    blocks: list[dict[str, Any]] = field(default_factory=list)
    confidence: float | None = None

    def best_text(self) -> str:
        """Return the richest textual representation available."""
        return self.markdown or self.text or self.html or ""


@dataclass
class EngineResponse:
    ok: bool
    engine_id: str
    pages: list[PageResult] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_json(self) -> str:
        payload = {
            "ok": self.ok,
            "engine_id": self.engine_id,
            "pages": [asdict(page) for page in self.pages],
            "meta": self.meta,
            "error": self.error,
        }
        return json.dumps(payload, ensure_ascii=False)


def read_request() -> dict[str, Any]:
    """Read the request object from stdin."""
    raw = sys.stdin.read()
    if not raw.strip():
        raise ValueError("empty request on stdin")
    return json.loads(raw)


def emit(response: EngineResponse) -> None:
    """Write the response object to stdout and flush."""
    sys.stdout.write(response.to_json())
    sys.stdout.flush()


def fail(engine_id: str, message: str, meta: dict[str, Any] | None = None) -> None:
    """Emit a structured failure and exit cleanly (exit code 0)."""
    emit(EngineResponse(ok=False, engine_id=engine_id, meta=meta or {}, error=message))
    sys.exit(0)


def main_wrapper(engine_id: str, handler) -> None:
    """Run an adapter handler with uniform error handling.

    ``handler(request) -> EngineResponse``
    """
    try:
        request = read_request()
    except Exception as exc:  # noqa: BLE001 - must never raise past here
        fail(engine_id, f"could not parse request: {exc}")

    try:
        response = handler(request)
    except Exception as exc:  # noqa: BLE001 - adapters are untrusted
        import traceback

        traceback.print_exc(file=sys.stderr)
        fail(engine_id, f"{type(exc).__name__}: {exc}")

    emit(response)
