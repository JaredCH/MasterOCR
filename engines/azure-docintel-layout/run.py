"""Azure Document Intelligence - prebuilt-layout (tables, selection marks)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from azure_docintel.run import handler as _handler  # noqa: E402
from _shared import EngineResponse, main_wrapper  # noqa: E402

ENGINE_ID = "azure-docintel-layout"


def handler(request: dict) -> EngineResponse:
    request.setdefault("options", {})["model"] = "prebuilt-layout"
    response = _handler(request)
    response.engine_id = ENGINE_ID
    return response


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
