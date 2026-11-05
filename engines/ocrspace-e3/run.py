"""OCR.space Engine 3 - 200+ languages, tables, Markdown output."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ocrspace.run import handler as _handler  # noqa: E402
from _shared import EngineResponse, main_wrapper  # noqa: E402

ENGINE_ID = "ocrspace-e3"


def handler(request: dict) -> EngineResponse:
    request.setdefault("options", {})["engine"] = 3
    response = _handler(request)
    response.engine_id = ENGINE_ID
    return response


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
