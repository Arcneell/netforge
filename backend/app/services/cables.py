"""Cables CRUD service."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cable import Cable
from app.schemas.cable import CableCreate, CableUpdate
from app.services.errors import catch_integrity_errors, not_found


async def list_cables(
    db: AsyncSession, in_stock_only: bool = False
) -> list[Cable]:
    base = select(Cable).order_by(Cable.id.desc())
    if in_stock_only:
        base = base.where(Cable.link_id.is_(None))
    result = await db.execute(base)
    return list(result.scalars().all())


async def get_cable(db: AsyncSession, cable_id: int) -> Cable:
    row = await db.get(Cable, cable_id)
    if row is None:
        not_found("Cable", cable_id)
    return row


async def get_cable_for_link(
    db: AsyncSession, link_id: int
) -> Cable | None:
    """`/api/links/{id}/cable` reads — None when the link has no cable yet."""
    result = await db.execute(select(Cable).where(Cable.link_id == link_id))
    return result.scalar_one_or_none()


async def create_cable(db: AsyncSession, payload: CableCreate) -> Cable:
    row = Cable(**payload.model_dump())
    db.add(row)
    with catch_integrity_errors():
        # cables_link_uniq → INTEGRITY_VIOLATION if you try to attach two
        # cables to the same link (rare but possible via raw API calls).
        await db.commit()
    await db.refresh(row)
    return row


async def update_cable(
    db: AsyncSession, cable_id: int, payload: CableUpdate
) -> Cable:
    row = await get_cable(db, cable_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    with catch_integrity_errors():
        await db.commit()
    await db.refresh(row)
    return row


async def delete_cable(db: AsyncSession, cable_id: int) -> None:
    row = await get_cable(db, cable_id)
    await db.delete(row)
    await db.commit()
