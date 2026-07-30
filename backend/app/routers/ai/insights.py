"""Infrastructure advisor — cached insights and on-demand refresh.

`GET /ai/insights` serves the last successful advisor run (annotated with
per-insight streak counts); `POST /ai/insights/refresh` fires a new run and
replaces the "latest" set in one transaction. The PDF rendering of the same
report lives in `pdf_export.py`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.db import get_session as get_db
from app.models.user import User, UserRole
from app.routers.ai.common import _require_ai_enabled, enforce_rate_limit, raise_ai_error
from app.schemas.ai import AdvisorReportRead, InsightRead, InsightsResponse
from app.services.ai.advisor import (
    compute_insight_streaks,
    list_latest_insights,
    run_advisor,
)
from app.services.ai.locale import language_instruction as _lang_for

router = APIRouter()


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
    await enforce_rate_limit(user.id)

    try:
        report = await run_advisor(
            db,
            user_id=user.id,
            language_instruction=_lang_for(accept_language),
        )
    except Exception as exc:
        raise_ai_error(exc, context="advisor run")

    return AdvisorReportRead(**report.__dict__)
