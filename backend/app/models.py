"""Pydantic request/response models for the API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class EngineInfo(BaseModel):
    id: str
    name: str
    vendor: str
    tier: int
    kind: str
    license: str
    license_note: str
    output: str
    cost_per_page_usd: float
    free_tier: str | None
    requires_key: str | None
    requires_gpu: bool
    requires_heavy: bool
    notes: str
    tags: list[str]
    available: bool
    unavailable_reason: str | None


class EngineListResponse(BaseModel):
    engines: list[EngineInfo]
    tier_counts: dict[str, int]
    available_count: int


class UploadResponse(BaseModel):
    document_id: str
    filename: str
    page_count: int
    classification: str
    pages: list[dict[str, Any]]


class RunRequest(BaseModel):
    engine_ids: list[str] = Field(default_factory=list)
    """Empty means: every available engine."""


class ScoreRequest(BaseModel):
    engine_id: str
    stars: int = Field(ge=1, le=5)
    notes: str | None = None


class DocumentSummary(BaseModel):
    id: str
    filename: str
    page_count: int
    classification: str
    created_at: float


# ---------------------------------------------------------------------------
# Phase 2: region capture
# ---------------------------------------------------------------------------


class RegionModel(BaseModel):
    """One named rectangle on a page, normalized 0..1."""

    id: str
    name: str
    kind: Literal["table", "line", "text", "keyvalue", "ignore"]
    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)
    page_number: int = Field(default=1, ge=1)
    engines: list[str] = Field(default_factory=list)
    manual_rows: list[float] = Field(default_factory=list)
    manual_cols: list[float] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)


class LayoutRequest(BaseModel):
    """Save the region set for one page."""

    page_number: int = Field(ge=1)
    page_width_pt: float = Field(gt=0)
    page_height_pt: float = Field(gt=0)
    regions: list[RegionModel]


class LayoutResponse(BaseModel):
    document_id: str
    page_number: int
    page_width_pt: float
    page_height_pt: float
    regions: list[RegionModel]


class RegionRunRequest(BaseModel):
    """Run OCR on the regions of one page.

    `region_ids` empty means every non-ignore region. `engine_ids` empty means
    each region's own engine list, falling back to the default cell engines.
    """

    page_number: int = Field(ge=1)
    region_ids: list[str] = Field(default_factory=list)
    engine_ids: list[str] = Field(default_factory=list)


class RegionRunStarted(BaseModel):
    run_id: str
    document_id: str
    page_number: int
    region_count: int


class TemplateCreateRequest(BaseModel):
    name: str
    document_id: str
    page_number: int = Field(ge=1)


class TemplateApplyRequest(BaseModel):
    page_number: int = Field(ge=1)
