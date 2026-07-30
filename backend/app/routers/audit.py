"""Audit log router — /api/audit (admin-only)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.db import get_session as get_db
from app.models.user import AuditAction, AuditLog, UserRole
from app.schemas.audit import AuditLogRead
from app.schemas.common import Page, PageParams
from app.services.errors import not_found

router = APIRouter(
    prefix="/audit",
    tags=["audit"],
    dependencies=[Depends(require_role(UserRole.admin))],
)


@router.get("", response_model=Page[AuditLogRead])
async def list_audit(
    page: PageParams = Depends(),
    entity: str | None = Query(default=None, min_length=1, max_length=50),
    entity_id: int | None = Query(default=None, gt=0),
    action: AuditAction | None = Query(default=None),
    user_id: int | None = Query(default=None, gt=0),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> Page[AuditLogRead]:
    # Naive datetimes coming in via query string are treated as UTC so they
    # can be compared against the timezone-aware `created_at` column
    # without TypeErrors (same mechanic as `routers/snapshots.py::compare`).
    if from_ is not None and from_.tzinfo is None:
        from_ = from_.replace(tzinfo=UTC)
    if to is not None and to.tzinfo is None:
        to = to.replace(tzinfo=UTC)

    base = select(AuditLog)
    count_q = select(func.count()).select_from(AuditLog)

    if entity is not None:
        base = base.where(AuditLog.entity == entity)
        count_q = count_q.where(AuditLog.entity == entity)
    if entity_id is not None:
        base = base.where(AuditLog.entity_id == entity_id)
        count_q = count_q.where(AuditLog.entity_id == entity_id)
    if action is not None:
        base = base.where(AuditLog.action == action)
        count_q = count_q.where(AuditLog.action == action)
    if user_id is not None:
        base = base.where(AuditLog.user_id == user_id)
        count_q = count_q.where(AuditLog.user_id == user_id)
    if from_ is not None:
        base = base.where(AuditLog.created_at >= from_)
        count_q = count_q.where(AuditLog.created_at >= from_)
    if to is not None:
        base = base.where(AuditLog.created_at <= to)
        count_q = count_q.where(AuditLog.created_at <= to)

    total = (await db.execute(count_q)).scalar() or 0
    result = await db.execute(
        base.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset(page.offset)
        .limit(page.limit)
    )
    return Page[AuditLogRead](
        items=[AuditLogRead.model_validate(r) for r in result.scalars().all()],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get("/{entry_id}", response_model=AuditLogRead)
async def get_audit(
    entry_id: int, db: AsyncSession = Depends(get_db)
) -> AuditLogRead:
    entry = await db.get(AuditLog, entry_id)
    if entry is None:
        not_found("Audit entry", entry_id)
    return AuditLogRead.model_validate(entry)
