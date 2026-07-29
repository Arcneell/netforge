"""AI link suggestions — scan, review, accept, reject.

The oldest AI surface: one scan proposes candidate `Link` rows, an admin
then promotes or dismisses each one. Every route here is admin-only; the
scan is additionally rate-limited because it burns a full LLM call.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.db import get_session as get_db
from app.models.user import User, UserRole
from app.routers.ai.common import (
    _GENERIC_502_DETAIL,
    _require_ai_enabled,
    enforce_rate_limit,
    logger,
)
from app.schemas.ai import LinkSuggestionRead, ScanReportRead
from app.schemas.link import LinkRead
from app.services.ai import AIProviderError, AIUnsupportedFeatureError
from app.services.ai.locale import language_instruction as _lang_for
from app.services.ai.suggest_links import (
    accept_suggestion,
    annotate_for_read,
    list_pending,
    reject_suggestion,
    run_suggest_links,
)

router = APIRouter()


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
    await enforce_rate_limit(user.id)

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
        # Full traceback goes to the server log; the client only gets a
        # generic message — exception reprs can leak internals (DSNs,
        # file paths, provider payloads).
        logger.exception("suggest-links scan crashed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=_GENERIC_502_DETAIL,
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
