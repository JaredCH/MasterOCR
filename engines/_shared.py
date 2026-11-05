"""Shared helpers for engine adapters.

Adapters are standalone scripts, so they import this module by path rather than
through the app package. Keeping the helpers here avoids duplicating the
response-building boilerplate 60 times.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make `app.engines.contract` importable when the adapter runs as a script.
_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.engines.contract import (  # noqa: E402
    EngineResponse,
    PageResult,
    main_wrapper,
    read_request,
)

__all__ = [
    "EngineResponse",
    "PageResult",
    "main_wrapper",
    "read_request",
    "pages_from_texts",
    "single_page_text",
]


def pages_from_texts(texts: list[str], *, markdown: bool = False) -> list[PageResult]:
    """Build PageResult objects from a list of per-page strings."""
    results: list[PageResult] = []
    for index, text in enumerate(texts, start=1):
        results.append(
            PageResult(
                page=index,
                text="" if markdown else text,
                markdown=text if markdown else None,
            )
        )
    return results


def single_page_text(text: str, *, markdown: bool = False) -> list[PageResult]:
    return pages_from_texts([text], markdown=markdown)
