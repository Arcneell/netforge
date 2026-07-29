"""AI usage dashboard — `GET /ai/usage`.

Read-only aggregation over the recorded AI runs (tokens, cost, latency)
bucketed by day / kind / provider. Purely historical data, so it answers
even with the feature switched off.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.db import get_session as get_db
from app.models.user import UserRole
from app.schemas.ai import UsageBucketRead, UsageReportRead, UsageTotalRead
from app.services.ai.usage import build_usage_report

router = APIRouter()


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
