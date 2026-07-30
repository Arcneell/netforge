"""VRFs CRUD service."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vrf import Vrf
from app.schemas.common import PageParams
from app.schemas.vrf import VrfCreate, VrfUpdate
from app.services.errors import catch_integrity_errors, not_found


async def list_vrfs(db: AsyncSession, page: PageParams) -> tuple[list[Vrf], int]:
    total = (await db.execute(select(func.count()).select_from(Vrf))).scalar() or 0
    result = await db.execute(
        select(Vrf).order_by(Vrf.name).offset(page.offset).limit(page.limit)
    )
    return list(result.scalars().all()), int(total)


async def get_vrf(db: AsyncSession, vrf_id: int) -> Vrf:
    row = await db.get(Vrf, vrf_id)
    if row is None:
        not_found("Vrf", vrf_id)
    return row


async def create_vrf(db: AsyncSession, payload: VrfCreate) -> Vrf:
    row = Vrf(**payload.model_dump())
    db.add(row)
    with catch_integrity_errors():
        await db.commit()
    await db.refresh(row)
    return row


async def update_vrf(db: AsyncSession, vrf_id: int, payload: VrfUpdate) -> Vrf:
    row = await get_vrf(db, vrf_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    with catch_integrity_errors():
        await db.commit()
    await db.refresh(row)
    return row


async def delete_vrf(db: AsyncSession, vrf_id: int) -> None:
    """Delete fails with 409 if any subnet still references the VRF.

    We use `ondelete=RESTRICT` on `subnets.vrf_id` so the DB raises an
    IntegrityError; `catch_integrity_errors` maps it to INTEGRITY_VIOLATION.
    Operators must clear the VRF from each subnet first (or delete those
    subnets) — silent cascade on a routing scope is too dangerous.
    """
    row = await get_vrf(db, vrf_id)
    await db.delete(row)
    with catch_integrity_errors():
        await db.commit()
