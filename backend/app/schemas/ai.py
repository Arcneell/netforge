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


class InsightEntityRef(BaseModel):
    """Free-shape reference to one of the indexed entities. `name` is the
    LLM's best guess at the time of the run — kept on the row so a deleted
    entity still renders a readable chip."""

    type: str
    id: int
    name: str | None = None


class InsightRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    severity: str
    category: str
    title: str
    description: str
    recommendation: str
    affected_entities: list[InsightEntityRef] | None = None
    created_at: datetime


class AdvisorReportRead(BaseModel):
    """Summary returned by POST /api/ai/insights/refresh."""

    run_id: int
    provider: str
    model: str
    raw_count: int
    persisted_count: int
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int


class InsightsResponse(BaseModel):
    """Latest insights with the run metadata that produced them.

    `run_id` is None when no advisor has ever been run successfully — the
    UI uses that to show the empty state ("Run the advisor to get started").
    `run_created_at` is the timestamp of that run, so the UI can render a
    "generated 3 days ago" hint and nudge the operator to re-run when the
    report is stale.
    """

    run_id: int | None
    run_created_at: datetime | None = None
    insights: list[InsightRead]


class QueryRequest(BaseModel):
    """Body of POST /api/ai/query."""

    question: str = Field(min_length=2, max_length=1000)


class QueryEntityRef(BaseModel):
    """Same shape as InsightEntityRef — kept as a separate class so future
    NL-query-specific fields (e.g. confidence per chip) can be added without
    co-evolving the advisor schema."""

    type: str
    id: int
    name: str | None = None


class QueryAnswerRead(BaseModel):
    """One-shot answer to a natural-language question."""

    answer: str
    referenced_entities: list[QueryEntityRef]
    provider: str
    model: str
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
