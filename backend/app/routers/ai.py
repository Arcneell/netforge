"""AI integration router — /api/ai.

Phase 1 surface:
- `GET /api/ai/status` — public status (enabled? provider? model?) so the
  UI can hide AI affordances cleanly.
- `POST /api/ai/suggestions/links/scan` — fire one suggest-links scan.
- `GET /api/ai/suggestions/links` — list pending suggestions.
- `POST /api/ai/suggestions/{id}/accept` — promote to a real Link.
- `POST /api/ai/suggestions/{id}/reject` — dismiss it.

All write paths are admin-only and rate-limited.
"""

from __future__ import annotations

import json as _json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("netforge.ai")

from app.auth.dependencies import get_current_user, require_role
from app.config import get_settings
from app.db import get_session as get_db
from app.models.user import User, UserRole
from app.schemas.ai import (
    ActionDraftCreate,
    ActionDraftRead,
    AdvisorReportRead,
    AIScheduleRead,
    AIScheduleUpsert,
    AIStatusRead,
    AITestResult,
    ConversationDetailRead,
    ConversationRead,
    ConversationTurnRead,
    ConversationUpdate,
    CsvColumnMapping,
    CsvDataQualityIssue,
    CsvMappingRequest,
    CsvMappingResponse,
    InsightRead,
    InsightsResponse,
    IntegrityIssueRead,
    IntegrityReportRead,
    LinkSuggestionRead,
    QueryAnswerRead,
    QueryRequest,
    ScanReportRead,
    UsageBucketRead,
    UsageReportRead,
    UsageTotalRead,
)
from app.schemas.link import LinkRead
from app.services.ai import AIProviderError, AIUnsupportedFeatureError, get_provider
from app.services.ai.actions import apply_draft, draft_action, reject_draft
from app.services.ai.advisor import (
    compute_insight_streaks,
    list_latest_insights,
    run_advisor,
)
from app.services.ai.conversations import (
    append_turn,
    create_conversation,
    delete_conversation,
    get_conversation,
    list_conversations,
    list_turns,
    rename_conversation,
)
from app.services.ai.csv_mapping import list_canonical_fields, run_mapping_suggestion
from app.services.ai.integrity import run_all_checks
from app.services.ai.locale import language_instruction as _lang_for
from app.services.ai.nl_query import run_query, run_query_streaming
from app.services.ai.pdf_export import build_filename as _pdf_filename
from app.services.ai.pdf_export import render_advisor_report
from app.services.ai.rate_limit import AIRateLimitExceeded, check_and_consume
from app.services.ai.suggest_links import (
    accept_suggestion,
    annotate_for_read,
    list_pending,
    reject_suggestion,
    run_suggest_links,
)
from app.services.ai.usage import build_usage_report

router = APIRouter(prefix="/ai", tags=["ai"])


def _require_ai_enabled() -> None:
    settings = get_settings()
    if not settings.ai_enabled:
        # 404 (not 503) so an unauthenticated probe can't fingerprint the
        # feature — matches how we hide /api/auth/dev when AUTH_PROVIDER!=dev.
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="AI not enabled")


def _require_drafts_enabled() -> None:
    """NL-to-action is the riskiest AI surface (apply mutates inventory).
    Returns 404 — same fingerprint-safe pattern as the master switch."""
    settings = get_settings()
    if not settings.ai_enabled or not settings.ai_drafts_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="AI drafts not enabled")


@router.get("/status", response_model=AIStatusRead, dependencies=[Depends(get_current_user)])
async def get_status() -> AIStatusRead:
    """Reports current AI configuration. Never raises — even when disabled
    we return a 200 with `enabled=false` so the UI can branch cleanly."""
    settings = get_settings()
    return AIStatusRead(
        enabled=settings.ai_enabled,
        provider=settings.ai_provider,
        model=settings.ai_model or "(default for provider)",
        drafts_enabled=settings.ai_enabled and settings.ai_drafts_enabled,
        scheduler_enabled=settings.ai_enabled and settings.ai_scheduler_enabled,
    )


@router.post(
    "/test",
    response_model=AITestResult,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def test_connection(user: User = Depends(get_current_user)) -> AITestResult:
    """Tiny ping call to the configured provider. Used by the Settings UI
    to verify "is my API key valid?" without burning tokens on a full scan."""
    _require_ai_enabled()
    try:
        check_and_consume(user.id)
    except AIRateLimitExceeded as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"rate limit exceeded, retry in {exc.retry_after_seconds}s",
        ) from exc

    import time

    provider = get_provider()
    t0 = time.monotonic()
    try:
        completion = await provider.call(
            system="You are a connection-test assistant. Reply with the single word 'pong'.",
            prompt="ping",
            max_tokens=16,
            temperature=0.0,
        )
    except AIProviderError as exc:
        return AITestResult(
            ok=False,
            provider=provider.name,
            model=provider.model,
            latency_ms=int((time.monotonic() - t0) * 1000),
            error=str(exc),
        )
    return AITestResult(
        ok=bool(completion.text or completion.tool_call),
        provider=provider.name,
        model=provider.model,
        latency_ms=int((time.monotonic() - t0) * 1000),
        error=None,
    )


@router.post(
    "/suggestions/links/scan",
    response_model=ScanReportRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def scan_links(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    accept_language: str | None = Header(default=None),
) -> ScanReportRead:
    _require_ai_enabled()
    try:
        check_and_consume(user.id)
    except AIRateLimitExceeded as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"rate limit exceeded, retry in {exc.retry_after_seconds}s",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc

    try:
        report = await run_suggest_links(
            db,
            user_id=user.id,
            language_instruction=_lang_for(accept_language),
        )
    except AIUnsupportedFeatureError as exc:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    except AIProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("suggest-links scan crashed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc

    return ScanReportRead(**report.__dict__)


@router.get(
    "/suggestions/links",
    response_model=list[LinkSuggestionRead],
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def list_suggestions(db: AsyncSession = Depends(get_db)) -> list[LinkSuggestionRead]:
    _require_ai_enabled()
    items = await list_pending(db)
    payload = await annotate_for_read(db, items)
    return [LinkSuggestionRead.model_validate(p) for p in payload]


@router.post(
    "/suggestions/{suggestion_id}/accept",
    response_model=LinkRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def accept(
    suggestion_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LinkRead:
    _require_ai_enabled()
    try:
        _, link = await accept_suggestion(db, suggestion_id=suggestion_id, user_id=user.id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return LinkRead.model_validate(link)


@router.post(
    "/suggestions/{suggestion_id}/reject",
    response_model=LinkSuggestionRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def reject(
    suggestion_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LinkSuggestionRead:
    _require_ai_enabled()
    try:
        suggestion = await reject_suggestion(
            db, suggestion_id=suggestion_id, user_id=user.id
        )
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return LinkSuggestionRead.model_validate(suggestion)


# --- Infrastructure advisor --------------------------------------------------

@router.get(
    "/insights",
    response_model=InsightsResponse,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def get_insights(db: AsyncSession = Depends(get_db)) -> InsightsResponse:
    """Latest cached advisor report. Empty when no run has ever succeeded.

    Each insight is annotated with a `streak_count` — how many consecutive
    recent runs it has appeared in. Operators can use the count to
    distinguish a brand-new finding from one that's been ignored for
    several runs in a row.
    """
    _require_ai_enabled()
    run_id, run_created_at, items = await list_latest_insights(db)
    streaks: dict[int, int] = {}
    if run_id is not None and items:
        streaks = await compute_insight_streaks(
            db, current_run_id=run_id, current_items=items
        )
    reads: list[InsightRead] = []
    for i in items:
        read = InsightRead.model_validate(i)
        read.streak_count = streaks.get(i.id, 1)
        reads.append(read)
    return InsightsResponse(
        run_id=run_id,
        run_created_at=run_created_at,
        insights=reads,
    )


@router.post(
    "/insights/refresh",
    response_model=AdvisorReportRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def refresh_insights(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    accept_language: str | None = Header(default=None),
) -> AdvisorReportRead:
    """Run a fresh advisor scan. Replaces the "latest" set in one transaction."""
    _require_ai_enabled()
    try:
        check_and_consume(user.id)
    except AIRateLimitExceeded as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"rate limit exceeded, retry in {exc.retry_after_seconds}s",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc

    try:
        report = await run_advisor(
            db,
            user_id=user.id,
            language_instruction=_lang_for(accept_language),
        )
    except AIUnsupportedFeatureError as exc:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    except AIProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("advisor run crashed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc

    return AdvisorReportRead(**report.__dict__)


# --- Natural-language query --------------------------------------------------

@router.post(
    "/query",
    response_model=QueryAnswerRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def ask_ai(
    payload: QueryRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    accept_language: str | None = Header(default=None),
) -> QueryAnswerRead:
    """Ask one free-text question grounded in the live inventory."""
    _require_ai_enabled()
    try:
        check_and_consume(user.id)
    except AIRateLimitExceeded as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"rate limit exceeded, retry in {exc.retry_after_seconds}s",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc

    # When a conversation_id is supplied, swap the client-supplied history
    # for the server-persisted turns of that conversation (the persisted
    # version is authoritative — the client may have been opened on a
    # different machine or refreshed). Server-side also enforces the same
    # 10-turn cap as the client.
    history = [t.model_dump() for t in payload.history]
    if payload.conversation_id is not None:
        await get_conversation(
            db, conversation_id=payload.conversation_id, user_id=user.id
        )  # 404 if not the user's
        persisted = await list_turns(
            db, conversation_id=payload.conversation_id
        )
        history = [
            {"role": t.role, "text": t.text} for t in persisted[-10:]
        ]
        await append_turn(
            db,
            conversation_id=payload.conversation_id,
            role="user",
            text=payload.question,
        )

    try:
        result = await run_query(
            db,
            user_id=user.id,
            question=payload.question,
            language_instruction=_lang_for(accept_language),
            history=history,
            lite_context=payload.lite_context,
        )
    except AIUnsupportedFeatureError as exc:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    except AIProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("nl-query crashed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc

    if payload.conversation_id is not None:
        await append_turn(
            db,
            conversation_id=payload.conversation_id,
            role="assistant",
            text=result.answer,
            entities=result.referenced_entities,
            latency_ms=result.latency_ms,
        )

    return QueryAnswerRead(**result.__dict__)


# --- Integrity checks --------------------------------------------------------


@router.get(
    "/integrity-checks",
    response_model=IntegrityReportRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def get_integrity_checks(
    db: AsyncSession = Depends(get_db),
    accept_language: str | None = Header(default=None),
) -> IntegrityReportRead:
    """Run the deterministic integrity checks (no LLM round-trip).

    Always returns a 200 — even when AI is disabled this endpoint stays up
    because it does not call any external provider. `Accept-Language`
    drives the issue titles + descriptions (FR/EN baked in)."""
    issues = await run_all_checks(db, accept_language=accept_language)
    return IntegrityReportRead(
        issues=[
            IntegrityIssueRead(
                severity=i.severity,
                category=i.category,
                title=i.title,
                description=i.description,
                recommendation=i.recommendation,
                affected_entities=i.affected_entities,
            )
            for i in issues
        ]
    )


# --- AI Usage dashboard ------------------------------------------------------


@router.get(
    "/usage",
    response_model=UsageReportRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def get_usage(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> UsageReportRead:
    """Aggregated AI usage over the last `days` days.

    Always returns a 200 (even when AI is disabled) — the data is historical;
    an admin who turned the feature off should still be able to see what they
    spent before.
    """
    report = await build_usage_report(db, days=days)
    return UsageReportRead(
        window_days=report.window_days,
        started_at=report.started_at,
        total=UsageTotalRead(**report.total.__dict__),
        by_day=[
            UsageBucketRead(key=b.key, totals=UsageTotalRead(**b.totals.__dict__))
            for b in report.by_day
        ],
        by_kind=[
            UsageBucketRead(key=b.key, totals=UsageTotalRead(**b.totals.__dict__))
            for b in report.by_kind
        ],
        by_provider=[
            UsageBucketRead(key=b.key, totals=UsageTotalRead(**b.totals.__dict__))
            for b in report.by_provider
        ],
    )


# --- CSV mapping assistant -------------------------------------------------


@router.post(
    "/csv/suggest-mapping",
    response_model=CsvMappingResponse,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def suggest_csv_mapping(
    payload: CsvMappingRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    accept_language: str | None = Header(default=None),
) -> CsvMappingResponse:
    """Ask the model to guess which NetForge field each CSV column maps to.

    Pure suggestion — the operator still renames their headers and runs the
    canonical import pipeline. Counts against the AI rate limit because it
    burns a full LLM call.
    """
    _require_ai_enabled()
    try:
        check_and_consume(user.id)
    except AIRateLimitExceeded as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"rate limit exceeded, retry in {exc.retry_after_seconds}s",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc

    if not list_canonical_fields(payload.entity):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"unknown entity for mapping: {payload.entity!r}",
        )

    try:
        result = await run_mapping_suggestion(
            db,
            user_id=user.id,
            entity=payload.entity,
            csv_columns=payload.csv_columns,
            sample_rows=payload.sample_rows,
            language_instruction=_lang_for(accept_language),
        )
    except AIUnsupportedFeatureError as exc:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    except AIProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("csv-mapping crashed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc

    return CsvMappingResponse(
        entity=result.entity,
        columns=[CsvColumnMapping(**c.__dict__) for c in result.columns],
        missing_required_fields=result.missing_required_fields,
        data_quality=[CsvDataQualityIssue(**i.__dict__) for i in result.data_quality],
        provider=result.provider,
        model=result.model,
        latency_ms=result.latency_ms,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
    )


# --- Scheduled AI runs -----------------------------------------------------


_SCHEDULABLE_KINDS = {"advisor", "suggest_links"}


@router.get(
    "/schedules",
    response_model=list[AIScheduleRead],
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def list_schedules(db: AsyncSession = Depends(get_db)) -> list[AIScheduleRead]:
    """List configured schedules. UI tolerates an empty list — kinds without
    a row have never been configured and default to disabled."""
    from sqlalchemy import select

    from app.models.ai import AISchedule

    rows = (
        (await db.execute(select(AISchedule).order_by(AISchedule.kind.asc())))
        .scalars()
        .all()
    )
    return [AIScheduleRead.model_validate(r) for r in rows]


@router.put(
    "/schedules/{kind}",
    response_model=AIScheduleRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def upsert_schedule(
    kind: str,
    payload: AIScheduleUpsert,
    db: AsyncSession = Depends(get_db),
) -> AIScheduleRead:
    """Create or update the schedule row for `kind`. Bounds enforced by the
    DB check constraint + pydantic; we just route the call."""
    if kind not in _SCHEDULABLE_KINDS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"kind must be one of {sorted(_SCHEDULABLE_KINDS)}",
        )

    from sqlalchemy import select

    from app.models.ai import AIRunKind, AISchedule, InsightSeverity

    kind_enum = AIRunKind(kind)
    row = (
        await db.execute(select(AISchedule).where(AISchedule.kind == kind_enum))
    ).scalar_one_or_none()
    if row is None:
        row = AISchedule(kind=kind_enum)
        db.add(row)
    row.enabled = payload.enabled
    row.interval_minutes = payload.interval_minutes
    row.webhook_url = (payload.webhook_url or "").strip() or None
    row.webhook_severity_threshold = InsightSeverity(payload.webhook_severity_threshold)
    await db.commit()
    await db.refresh(row)
    return AIScheduleRead.model_validate(row)


# --- NL-to-action drafts ---------------------------------------------------


@router.post(
    "/drafts",
    response_model=ActionDraftRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def create_draft(
    payload: ActionDraftCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    accept_language: str | None = Header(default=None),
) -> ActionDraftRead:
    """Ask the LLM to draft one CRUD action from a free-text prompt.

    NEVER executes the action — the resulting row sits at `status=pending`
    until an admin POSTs to `/drafts/{id}/apply`."""
    _require_drafts_enabled()
    try:
        check_and_consume(user.id)
    except AIRateLimitExceeded as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"rate limit exceeded, retry in {exc.retry_after_seconds}s",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc

    try:
        draft = await draft_action(
            db,
            user_id=user.id,
            prompt=payload.prompt,
            language_instruction=_lang_for(accept_language),
        )
    except AIUnsupportedFeatureError as exc:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    except AIProviderError as exc:
        # 422 — the call itself worked, the model just couldn't produce a
        # valid draft. Keeping 502 for true provider/HTTP failures.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.exception("draft_action crashed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc
    return ActionDraftRead.model_validate(draft)


@router.get(
    "/drafts",
    response_model=list[ActionDraftRead],
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def list_drafts(db: AsyncSession = Depends(get_db)) -> list[ActionDraftRead]:
    """Return drafts, newest first. The UI typically filters to pending."""
    from sqlalchemy import select

    from app.models.ai import AIActionDraft

    rows = (
        (
            await db.execute(
                select(AIActionDraft).order_by(AIActionDraft.created_at.desc()).limit(200)
            )
        )
        .scalars()
        .all()
    )
    return [ActionDraftRead.model_validate(r) for r in rows]


@router.post(
    "/drafts/{draft_id}/apply",
    response_model=ActionDraftRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def apply_draft_route(
    draft_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ActionDraftRead:
    """Execute the draft against the inventory. Idempotent in the sense
    that the second call returns 409 — the first apply marks the row
    `applied`.

    Error mapping:
        404 — draft not found
        409 — draft already applied/rejected, OR a DB-level conflict raised
              by the applier (subnet overlap, duplicate site code, missing
              referenced VLAN, …). The draft row is marked `failed` and the
              `error_message` is surfaced to the operator.
        502 — anything else (transient DB error, unexpected internal bug).
              The draft is also marked `failed`; the message is in `detail`
              so the UI can show it.
    """
    from sqlalchemy.exc import IntegrityError

    _require_drafts_enabled()
    try:
        draft = await apply_draft(db, draft_id=draft_id, user_id=user.id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except IntegrityError as exc:
        # The applier already rolled back and marked the draft as failed —
        # surface the constraint name + message so the UI can explain
        # "subnet overlaps with 10.0.0.0/24" instead of a generic 502.
        message = str(getattr(exc, "orig", exc)) or "database integrity violation"
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=message
        ) from exc
    except Exception as exc:
        logger.exception("draft apply crashed (draft_id=%s)", draft_id)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc
    return ActionDraftRead.model_validate(draft)


@router.post(
    "/drafts/{draft_id}/reject",
    response_model=ActionDraftRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def reject_draft_route(
    draft_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ActionDraftRead:
    """Mark the draft as rejected — the operator declined to apply it."""
    _require_drafts_enabled()
    try:
        draft = await reject_draft(db, draft_id=draft_id, user_id=user.id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ActionDraftRead.model_validate(draft)


# --- PDF export ------------------------------------------------------------


@router.get(
    "/insights/export.pdf",
    response_class=Response,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def export_insights_pdf(
    db: AsyncSession = Depends(get_db),
    accept_language: str | None = Header(default=None),
) -> Response:
    """Render the latest advisor report as a PDF.

    Gated on `AI_ENABLED` — same pattern as the rest of the advisor surface.
    Returns 404 when AI is disabled or when no advisor run has ever
    succeeded (matches the empty state the UI already handles). The PDF is
    rendered in the operator's UI language — FR/EN, falls back to EN.
    """
    _require_ai_enabled()
    run_id, run_created_at, items = await list_latest_insights(db)
    if run_id is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="no advisor run has succeeded yet"
        )
    # Re-use the parsing logic the locale shim already implements.
    from app.services.ai.locale import _parse_primary_tag

    locale = _parse_primary_tag(accept_language)
    pdf_bytes = render_advisor_report(
        run_created_at=run_created_at,
        insights=items,
        locale=locale,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{_pdf_filename(run_created_at)}"',
        },
    )


# --- Streaming Ask AI ------------------------------------------------------


@router.post(
    "/query/stream",
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def ask_ai_stream(
    payload: QueryRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    accept_language: str | None = Header(default=None),
) -> StreamingResponse:
    """Server-Sent-Events variant of `/api/ai/query`.

    The client receives incremental `delta` frames as the model writes,
    plus a final `done` frame carrying token usage + latency. Tool calls
    are NOT used in this path — the answer is Markdown text only (entity
    references stay inline). The non-streaming endpoint remains available
    for callers that need the structured `referenced_entities` chips.
    """
    _require_ai_enabled()
    try:
        check_and_consume(user.id)
    except AIRateLimitExceeded as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"rate limit exceeded, retry in {exc.retry_after_seconds}s",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc

    # If a conversation_id is supplied, swap the client-supplied history
    # for the persisted turns and record the user prompt BEFORE the stream
    # starts. The assistant text is accumulated below from the delta
    # frames and persisted on the `done` event.
    history = [t.model_dump() for t in payload.history]
    if payload.conversation_id is not None:
        await get_conversation(
            db, conversation_id=payload.conversation_id, user_id=user.id
        )
        persisted = await list_turns(
            db, conversation_id=payload.conversation_id
        )
        history = [
            {"role": t.role, "text": t.text} for t in persisted[-10:]
        ]
        await append_turn(
            db,
            conversation_id=payload.conversation_id,
            role="user",
            text=payload.question,
        )

    async def _stream():
        # SSE preamble — a no-op comment frame (`: ...\n\n`) sent before any
        # real event. Forces the HTTP layer to flush response headers and the
        # 2-KB-or-so of headroom that some proxies (notably nginx with
        # `proxy_buffering` left on, and some Node http-proxy stacks)
        # accumulate before delivering the first byte to the client. Without
        # it, very small first deltas can sit in the pipeline until the next
        # one piles on top.
        yield ": ok\n\n"

        import asyncio as _asyncio

        # Accumulate the assistant's emitted text so we can persist a
        # single AIConversationTurn on the `done` frame. The streaming
        # provider sends one `delta` frame per token chunk; concatenating
        # them reconstructs the full reply.
        assistant_text_parts: list[str] = []
        done_latency_ms: int | None = None
        try:
            async for event_name, data in run_query_streaming(
                db,
                user_id=user.id,
                question=payload.question,
                history=history,
                language_instruction=_lang_for(accept_language),
                lite_context=payload.lite_context,
            ):
                if event_name == "delta" and isinstance(data, dict):
                    delta_text = data.get("text") or data.get("delta") or ""
                    if isinstance(delta_text, str):
                        assistant_text_parts.append(delta_text)
                if event_name == "done" and isinstance(data, dict):
                    latency = data.get("latency_ms")
                    if isinstance(latency, int):
                        done_latency_ms = latency
                # SSE wire format: `event:` line is optional, `data:` line
                # carries the JSON body, blank line terminates the frame.
                yield f"event: {event_name}\ndata: {_json.dumps(data)}\n\n"
                # Cooperative yield: lets the StreamingResponse writer
                # actually drain the chunk to the socket before we wait on
                # the next provider delta. Cheap insurance against the event
                # loop holding multiple chunks in one tick.
                await _asyncio.sleep(0)
        except Exception as exc:
            logger.exception("nl-query stream crashed")
            yield f"event: error\ndata: {_json.dumps({'message': str(exc)})}\n\n"
        finally:
            # Persist the assistant turn even on partial / interrupted
            # streams — the operator sees what the model managed to
            # produce when they reload the conversation, and the
            # comparison with `expected length` lets them decide
            # whether to retry. Empty completions are skipped.
            if payload.conversation_id is not None:
                full_text = "".join(assistant_text_parts).strip()
                if full_text:
                    try:
                        await append_turn(
                            db,
                            conversation_id=payload.conversation_id,
                            role="assistant",
                            text=full_text,
                            latency_ms=done_latency_ms,
                        )
                    except Exception:
                        # The stream is already over from the client's
                        # POV — losing the persisted assistant turn is a
                        # bug but not a request-level error. Logged so
                        # ops can investigate without breaking the user
                        # response.
                        logger.exception(
                            "failed to persist assistant turn for "
                            "conversation_id=%s",
                            payload.conversation_id,
                        )

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            # Tell nginx (and any other reverse proxy) NOT to buffer — SSE
            # only works end-to-end when each frame is flushed immediately.
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# --- Ask-AI conversation history -------------------------------------------
#
# Conversations are per-user persistent threads. They sit alongside the
# existing one-shot /query and /query/stream endpoints — neither route
# requires a conversation_id, but when one is supplied the user + assistant
# turns are persisted into the matching `ai_conversations` row and the
# server uses the persisted history instead of the client-supplied one.


@router.get(
    "/conversations",
    response_model=list[ConversationRead],
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def list_user_conversations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ConversationRead]:
    """Return the operator's most-recent conversations, newest first.

    Each row carries `turn_count` + a short preview so the sidebar can
    render without N+1 round-trips for the per-conversation details.
    """
    _require_ai_enabled()
    rows = await list_conversations(db, user_id=user.id, limit=limit)
    return [ConversationRead(**r) for r in rows]


@router.post(
    "/conversations",
    response_model=ConversationRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def create_user_conversation(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationRead:
    """Open a fresh empty conversation. Title is filled lazily when the
    first user turn lands via POST /api/ai/query{,/stream} with the new
    `conversation_id` parameter."""
    _require_ai_enabled()
    conv = await create_conversation(db, user_id=user.id)
    return ConversationRead(
        id=conv.id,
        title=conv.title or "",
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        turn_count=0,
        preview=None,
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetailRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def get_user_conversation(
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationDetailRead:
    """Load one conversation with every turn embedded."""
    _require_ai_enabled()
    conv = await get_conversation(
        db, conversation_id=conversation_id, user_id=user.id
    )
    turns = await list_turns(db, conversation_id=conversation_id)
    return ConversationDetailRead(
        id=conv.id,
        title=conv.title or "",
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        turn_count=len(turns),
        preview=None,
        turns=[
            ConversationTurnRead(
                id=t.id,
                role=t.role,
                text=t.text,
                entities=t.entities or [],
                latency_ms=t.latency_ms,
                created_at=t.created_at,
            )
            for t in turns
        ],
    )


@router.patch(
    "/conversations/{conversation_id}",
    response_model=ConversationRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def rename_user_conversation(
    conversation_id: int,
    payload: ConversationUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationRead:
    """Rename a conversation. Only the title is editable today."""
    _require_ai_enabled()
    conv = await rename_conversation(
        db,
        conversation_id=conversation_id,
        user_id=user.id,
        title=payload.title,
    )
    return ConversationRead(
        id=conv.id,
        title=conv.title or "",
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        turn_count=0,
        preview=None,
    )


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def delete_user_conversation(
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Erase a conversation + every turn under it (CASCADE)."""
    _require_ai_enabled()
    await delete_conversation(
        db, conversation_id=conversation_id, user_id=user.id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
