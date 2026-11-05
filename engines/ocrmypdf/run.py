"""OCRmyPDF - deskew/cleanup plus Tesseract, then read back the text layer."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "ocrmypdf"


def handler(request: dict) -> EngineResponse:
    import pymupdf

    with tempfile.TemporaryDirectory() as tmp:
        output_pdf = Path(tmp) / "ocr.pdf"
        result = subprocess.run(
            [
                "ocrmypdf",
                "--force-ocr",
                "--deskew",
                "--clean",
                "--optimize",
                "0",
                "--output-type",
                "pdf",
                request["pdf_path"],
                str(output_pdf),
            ],
            capture_output=True,
            text=True,
            timeout=280,
            check=False,
        )
        if result.returncode != 0 or not output_pdf.exists():
            return EngineResponse(
                ok=False,
                engine_id=ENGINE_ID,
                error=f"ocrmypdf failed: {result.stderr.strip()[:800]}",
            )

        pages: list[PageResult] = []
        with pymupdf.open(output_pdf) as doc:
            for index in range(doc.page_count):
                pages.append(
                    PageResult(page=index + 1, text=doc.load_page(index).get_text("text"))
                )

    return EngineResponse(ok=True, engine_id=ENGINE_ID, pages=pages)


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
