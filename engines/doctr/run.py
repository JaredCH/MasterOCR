"""docTR - DBNet detector plus PARSeq recognizer."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "doctr"


def handler(request: dict) -> EngineResponse:
    from doctr.io import DocumentFile
    from doctr.models import ocr_predictor

    model = ocr_predictor(
        det_arch="db_resnet50",
        reco_arch="parseq",
        pretrained=True,
        assume_straight_pages=False,
    )

    document = DocumentFile.from_pdf(request["pdf_path"])
    result = model(document)
    exported = result.export()

    pages: list[PageResult] = []
    for index, page in enumerate(exported.get("pages", []), start=1):
        lines = []
        blocks = []
        confidences = []
        for block in page.get("blocks", []):
            for line in block.get("lines", []):
                text = " ".join(
                    word.get("value", "") for word in line.get("words", [])
                )
                confidence = line.get("confidence")
                if confidence is not None:
                    confidences.append(float(confidence))
                lines.append(text)
                blocks.append(
                    {
                        "type": "line",
                        "text": text,
                        "bbox": line.get("geometry"),
                        "confidence": confidence,
                    }
                )
        pages.append(
            PageResult(
                page=index,
                text="\n".join(lines),
                blocks=blocks,
                confidence=sum(confidences) / len(confidences) if confidences else None,
            )
        )

    return EngineResponse(ok=True, engine_id=ENGINE_ID, pages=pages)


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
