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
    """Light status response so the UI can hide AI features when disabled.

    `enabled` is the master switch; the granular sub-flags let the operator
    keep some AI features but disable others (e.g. read-only mode that
    keeps the advisor but kills the NL-to-action drafts surface)."""

    enabled: bool
    provider: str
    model: str
    drafts_enabled: bool = True
    scheduler_enabled: bool = True


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
    # How many consecutive recent advisor runs this finding has appeared
    # in (including the current one). 1 = brand-new, ≥ 2 = recurring.
    # Computed at query time by `advisor.compute_insight_streaks`; never
    # stored, so a re-run on an unchanged topology produces a higher
    # number without backfilling old rows.
    streak_count: int = 1


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


class QueryHistoryTurn(BaseModel):
    """One past turn the client wants the model to remember. The server is
    stateless — the frontend owns the conversation, replays the last few
    turns on each request, and decides when to "start a new chat" (i.e. send
    an empty `history`)."""

    role: str = Field(pattern="^(user|assistant)$")
    text: str = Field(min_length=1, max_length=4000)


class QueryRequest(BaseModel):
    """Body of POST /api/ai/query.

    `history` lets the operator have a follow-up conversation — capped at 10
    turns (≈ 5 user/assistant pairs) so the prompt doesn't balloon. Older
    turns are dropped client-side.

    `lite_context`, when true, strips the inventory snapshot down to bare
    identifiers (id + name + code + parent id where relevant) before
    handing it to the model. Useful for token-cost-sensitive deployments
    or privacy-conscious operators who don't want vendor / model / MAC /
    serial details leaving their network. The model can still answer
    structural questions ("what's on VLAN 10?") but loses the ability to
    reason over free-text fields it no longer receives."""

    question: str = Field(min_length=2, max_length=1000)
    history: list[QueryHistoryTurn] = Field(default_factory=list, max_length=10)
    lite_context: bool = False
    # When set, the backend persists this exchange (user + assistant turns)
    # into the matching `ai_conversations` row and uses the last N
    # persisted turns as the effective history (the client-supplied
    # `history` field is ignored). When unset, the call stays stateless
    # — the operator can still see the local in-browser history but
    # nothing is stored server-side.
    conversation_id: int | None = Field(default=None, gt=0)


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


# --- Conversation history --------------------------------------------------


class ConversationTurnRead(BaseModel):
    """One turn of a persisted Ask-AI conversation."""

    id: int
    role: str
    text: str
    entities: list[QueryEntityRef] = Field(default_factory=list)
    latency_ms: int | None = None
    created_at: datetime


class ConversationRead(BaseModel):
    """Conversation list-item — no turns embedded.

    The list endpoint surfaces these so the sidebar can render quickly
    without dragging the full transcript across the wire on every load."""

    id: int
    title: str
    created_at: datetime
    updated_at: datetime
    turn_count: int
    preview: str | None = None


class ConversationDetailRead(ConversationRead):
    """A single conversation with every turn embedded — used by the
    "load this thread" path."""

    turns: list[ConversationTurnRead]


class ConversationUpdate(BaseModel):
    """PATCH body — only the title is editable today."""

    title: str = Field(min_length=1, max_length=200)


# --- AI Usage dashboard ------------------------------------------------------


class UsageTotalRead(BaseModel):
    """Aggregate counters for one bucket (or the whole window)."""

    calls: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    success: int
    failure: int
    avg_latency_ms: int


class UsageBucketRead(BaseModel):
    """Generic dimension bucket. `key` is "YYYY-MM-DD" for day, the enum value
    for kind, the provider name otherwise."""

    key: str
    totals: UsageTotalRead


class UsageReportRead(BaseModel):
    """Response of GET /api/ai/usage. Empty `by_*` lists when the window has
    no calls — the UI uses that to render the "no usage yet" state."""

    window_days: int
    started_at: datetime
    total: UsageTotalRead
    by_day: list[UsageBucketRead]
    by_kind: list[UsageBucketRead]
    by_provider: list[UsageBucketRead]


# --- Integrity checks ------------------------------------------------------


class IntegrityIssueRead(BaseModel):
    """A deterministic check finding. Same surface as `InsightRead` so the
    frontend re-uses the existing card components without branching."""

    severity: str
    category: str
    title: str
    description: str
    recommendation: str
    affected_entities: list[InsightEntityRef]


class IntegrityReportRead(BaseModel):
    """Wrapper for the integrity-checks endpoint. Empty list when nothing
    is wrong — the UI renders the "all clear" state."""

    issues: list[IntegrityIssueRead]


# --- CSV mapping assistant -------------------------------------------------


class CsvMappingRequest(BaseModel):
    """Body of POST /api/ai/csv/suggest-mapping.

    `entity` is one of the import-pipeline entities (sites, vlans, …).
    `csv_columns` is the foreign header row as-is. `sample_rows` is a few
    sample lines aligned with the headers — the LLM uses the cell shape
    (CIDR vs IP, MAC notation, boolean encoding) to disambiguate."""

    entity: str = Field(min_length=1, max_length=40)
    csv_columns: list[str] = Field(min_length=1, max_length=80)
    sample_rows: list[list[str]] = Field(default_factory=list, max_length=10)


class CsvColumnMapping(BaseModel):
    """One column → field decision."""

    csv_column: str
    suggested_field: str | None
    confidence: float = Field(ge=0, le=1)
    notes: str


class CsvDataQualityIssue(BaseModel):
    """One data-quality observation surfaced by the mapper.

    Two complementary sources feed this:
      - **Deterministic checks** (`csv_mapping.run_local_data_quality`) catch
        obviously wrong cells in the sample: empty required fields, malformed
        CIDR/IPv4/MAC, duplicate values in unique columns.
      - **LLM observations** flag higher-level issues the deterministic
        checks miss: mixed unit conventions, inconsistent casing, suspicious
        outliers.
    """

    severity: str  # "info" | "warning" | "critical"
    column: str | None  # null when the issue is row-level (e.g. duplicate)
    issue: str  # short headline, e.g. "invalid CIDR"
    details: str  # human-readable explanation
    sample_values: list[str] = Field(default_factory=list, max_length=5)
    affected_row_count: int = 0
    source: str  # "local" (deterministic) | "llm"


class CsvMappingResponse(BaseModel):
    """Response of POST /api/ai/csv/suggest-mapping."""

    entity: str
    columns: list[CsvColumnMapping]
    missing_required_fields: list[str]
    data_quality: list[CsvDataQualityIssue] = Field(default_factory=list)
    provider: str
    model: str
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int


# --- Scheduled AI runs -----------------------------------------------------


class AIScheduleRead(BaseModel):
    """Configuration of one recurring AI task."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str  # "advisor" | "suggest_links"
    enabled: bool
    interval_minutes: int
    webhook_url: str | None
    webhook_severity_threshold: str
    last_run_at: datetime | None
    last_run_id: int | None


class AIScheduleUpsert(BaseModel):
    """Body of PUT /api/ai/schedules/{kind}.

    `enabled` may be flipped without touching the other fields. The bounds
    on `interval_minutes` mirror the DB check constraint."""

    enabled: bool = False
    interval_minutes: int = Field(ge=15, le=10080, default=1440)
    # Kept as a plain string here because the meaningful validation (http(s)
    # scheme + SSRF target check, which needs DNS) is async — the router's
    # upsert handler runs `check_outbound_url_async` and answers 422 on a
    # refused URL, so bad targets fail loudly at save time instead of
    # silently at dispatch time.
    webhook_url: str | None = Field(default=None, max_length=2000)
    webhook_severity_threshold: str = Field(
        default="warning", pattern="^(info|warning|critical)$"
    )


# --- NL-to-action drafts ---------------------------------------------------


class ActionDraftCreate(BaseModel):
    """Body of POST /api/ai/drafts. The operator types a free-text request;
    the server asks the LLM to draft one CRUD action."""

    prompt: str = Field(min_length=4, max_length=2000)


class ActionDraftRead(BaseModel):
    """One drafted action awaiting (or past) review."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None
    prompt: str
    intent: str
    payload: dict
    status: str
    error_code: str | None
    error_message: str | None
    applied_resource: str | None
    applied_by_user_id: int | None
    applied_at: datetime | None
    created_at: datetime
