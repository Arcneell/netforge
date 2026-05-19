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

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("netforge.ai")

from app.auth.dependencies import get_current_user, require_role
from app.config import get_settings
from app.db import get_session as get_db
from app.models.user import User, UserRole
from app.schemas.ai import (
    AdvisorReportRead,
    AIStatusRead,
    AITestResult,
    InsightRead,
    InsightsResponse,
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
from app.services.ai.advisor import list_latest_insights, run_advisor
from app.services.ai.locale import language_instruction as _lang_for
from app.services.ai.nl_query import run_query
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


@router.get("/status", response_model=AIStatusRead, dependencies=[Depends(get_current_user)])
async def get_status() -> AIStatusRead:
    """Reports current AI configuration. Never raises — even when disabled
    we return a 200 with `enabled=false` so the UI can branch cleanly."""
    settings = get_settings()
    return AIStatusRead(
        enabled=settings.ai_enabled,
        provider=settings.ai_provider,
        model=settings.ai_model or "(default for provider)",
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
    """Latest cached advisor report. Empty when no run has ever succeeded."""
    _require_ai_enabled()
    run_id, run_created_at, items = await list_latest_insights(db)
    return InsightsResponse(
        run_id=run_id,
        run_created_at=run_created_at,
        insights=[InsightRead.model_validate(i) for i in items],
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

    try:
        result = await run_query(
            db,
            user_id=user.id,
            question=payload.question,
            language_instruction=_lang_for(accept_language),
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

    return QueryAnswerRead(**result.__dict__)


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
