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

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.config import get_settings
from app.db import get_session as get_db
from app.models.user import User, UserRole
from app.schemas.ai import AIStatusRead, LinkSuggestionRead, ScanReportRead
from app.schemas.link import LinkRead
from app.services.ai import AIProviderError, AIUnsupportedFeatureError
from app.services.ai.rate_limit import AIRateLimitExceeded, check_and_consume
from app.services.ai.suggest_links import (
    accept_suggestion,
    annotate_for_read,
    list_pending,
    reject_suggestion,
    run_suggest_links,
)

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
    "/suggestions/links/scan",
    response_model=ScanReportRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def scan_links(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
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
        report = await run_suggest_links(db, user_id=user.id)
    except AIUnsupportedFeatureError as exc:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    except AIProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

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
