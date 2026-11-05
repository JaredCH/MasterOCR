"""AWS Textract - DetectDocumentText with optional table analysis."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import EngineResponse, PageResult, main_wrapper  # noqa: E402

ENGINE_ID = "aws-textract"


def handler(request: dict) -> EngineResponse:
    import boto3

    credentials = request["credentials"]
    if not credentials.get("aws_access_key_id"):
        return EngineResponse(
            ok=False, engine_id=ENGINE_ID, error="Missing AWS_ACCESS_KEY_ID"
        )

    client = boto3.client(
        "textract",
        aws_access_key_id=credentials.get("aws_access_key_id"),
        aws_secret_access_key=credentials.get("aws_secret_access_key"),
        region_name=request.get("options", {}).get("region", "us-east-1"),
    )

    pages: list[PageResult] = []
    for index, image_path in enumerate(request["page_images"], start=1):
        with open(image_path, "rb") as handle:
            payload = handle.read()

        response = client.analyze_document(
            Document={"Bytes": payload},
            FeatureTypes=["TABLES"],
        )

        lines = [
            block["Text"]
            for block in response.get("Blocks", [])
            if block.get("BlockType") == "LINE"
        ]
        pages.append(PageResult(page=index, text="\n".join(lines)))

    return EngineResponse(ok=True, engine_id=ENGINE_ID, pages=pages)


if __name__ == "__main__":
    main_wrapper(ENGINE_ID, handler)
