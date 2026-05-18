"""Pydantic schemas for the AI surface (read-only response shapes)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LinkSuggestionRead(BaseModel):
    """Pending / resolved AI suggestion exposed to the client.

    The denormalised `*_label` / `*_switch_name` fields are filled by
    `services.ai.suggest_links.serialize_for_read` — the frontend would
    otherwise have to fetch every port individually to render the panel.
    Missing labels (port deleted between scan + read) come back as None.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    port_a_id: int
    port_b_id: int
    port_a_label: str | None = None
    port_b_label: str | None = None
    switch_a_name: str | None = None
    switch_b_name: str | None = None
    link_type: str
    confidence: float = Field(ge=0, le=1)
    reasoning: str
    status: str
    accepted_link_id: int | None
    resolved_by_user_id: int | None
    resolved_at: datetime | None
    created_at: datetime


class ScanReportRead(BaseModel):
    """Summary returned after a /scan call."""

    run_id: int
    provider: str
    model: str
    raw_count: int
    persisted_count: int
    skipped_count: int
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int


class AIStatusRead(BaseModel):
    """Light status response so the UI can hide AI features when disabled."""

    enabled: bool
    provider: str
    model: str


class AITestResult(BaseModel):
    """Result of POST /api/ai/test — a single ping call to the configured
    provider to verify the API key and model name are valid before letting
    the user trigger a real (more expensive) scan."""

    ok: bool
    provider: str
    model: str
    latency_ms: int
    error: str | None = None
