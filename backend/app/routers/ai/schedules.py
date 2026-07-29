"""Scheduled AI runs — list + upsert the per-kind schedule rows.

The background scheduler reads these rows to decide when to fire an
advisor or suggest-links run and where to POST the notification webhook.
Only the two schedulable kinds are accepted.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.config import get_settings
from app.db import get_session as get_db
from app.models.ai import AIRunKind, AISchedule, InsightSeverity
from app.models.user import UserRole
from app.schemas.ai import AIScheduleRead, AIScheduleUpsert
from app.utils.ssrf import UnsafeOutboundURL, check_outbound_url_async

router = APIRouter()

_SCHEDULABLE_KINDS = {"advisor", "suggest_links"}


@router.get(
    "/schedules",
    response_model=list[AIScheduleRead],
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def list_schedules(db: AsyncSession = Depends(get_db)) -> list[AIScheduleRead]:
    """List configured schedules. UI tolerates an empty list — kinds without
    a row have never been configured and default to disabled."""
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

    # Validate the webhook URL at write time (scheme http(s), host present,
    # not a private / loopback / metadata target). The dispatch path pins
    # and re-checks anyway, but failing HERE gives the admin a visible 422
    # instead of a silent refusal buried in the scheduler logs when the
    # notification eventually fires.
    webhook_url = (payload.webhook_url or "").strip() or None
    if webhook_url is not None:
        try:
            await check_outbound_url_async(
                webhook_url,
                allow_private=get_settings().webhook_allow_private_targets,
            )
        except UnsafeOutboundURL as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"webhook_url rejected: {exc}",
            ) from exc

    kind_enum = AIRunKind(kind)
    row = (
        await db.execute(select(AISchedule).where(AISchedule.kind == kind_enum))
    ).scalar_one_or_none()
    if row is None:
        row = AISchedule(kind=kind_enum)
        db.add(row)
    row.enabled = payload.enabled
    row.interval_minutes = payload.interval_minutes
    row.webhook_url = webhook_url
    row.webhook_severity_threshold = InsightSeverity(payload.webhook_severity_threshold)
    await db.commit()
    await db.refresh(row)
    return AIScheduleRead.model_validate(row)
