"""Pydantic request/response models for the API."""

from __future__ import annotations

from typing import Any

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
