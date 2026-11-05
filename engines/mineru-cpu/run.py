"""MinerU CPU pipeline - full document parsing, high structural fidelity."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "mineru-cpu"


def handler(request: dict) -> EngineResponse:
    with tempfile.TemporaryDirectory() as tmp:
        output_dir = Path(tmp) / "out"
        result = subprocess.run(
            [
                "mineru",
                "-p",
                request["pdf_path"],
                "-o",
                str(output_dir),
                "-m",
                "auto",
                "-b",
                "pipeline",
            ],
            capture_output=True,
            text=True,
            timeout=580,
            check=False,
        )
        if result.returncode != 0:
            return EngineResponse(
                ok=False,
                engine_id=ENGINE_ID,
                error=f"mineru failed: {result.stderr.strip()[:800]}",
            )

        markdown_files = sorted(output_dir.rglob("*.md"))
        if not markdown_files:
            return EngineResponse(
                ok=False, engine_id=ENGINE_ID, error="MinerU produced no Markdown"
            )

        pages = [
            PageResult(page=index, markdown=path.read_text(encoding="utf-8"))
            for index, path in enumerate(markdown_files, start=1)
        ]

    return EngineResponse(ok=True, engine_id=ENGINE_ID, pages=pages)


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
