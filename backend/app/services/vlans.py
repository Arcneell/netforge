"""VLANs service."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vlan import Vlan
from app.schemas.common import PageParams
from app.schemas.vlan import VlanCreate, VlanUpdate
from app.services.errors import catch_integrity_errors, not_found


async def list_vlans(db: AsyncSession, page: PageParams) -> tuple[list[Vlan], int]:
    total = (await db.execute(select(func.count()).select_from(Vlan))).scalar() or 0
    result = await db.execute(
        select(Vlan).order_by(Vlan.vlan_id).offset(page.offset).limit(page.limit)
    )
    return list(result.scalars().all()), int(total)


async def get_vlan(db: AsyncSession, vlan_pk: int) -> Vlan:
    vlan = await db.get(Vlan, vlan_pk)
    if vlan is None:
        not_found("VLAN", vlan_pk)
    return vlan


async def create_vlan(db: AsyncSession, payload: VlanCreate) -> Vlan:
    vlan = Vlan(**payload.model_dump())
    db.add(vlan)
    with catch_integrity_errors():
        await db.commit()
    await db.refresh(vlan)
    return vlan


async def update_vlan(db: AsyncSession, vlan_pk: int, payload: VlanUpdate) -> Vlan:
    vlan = await get_vlan(db, vlan_pk)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(vlan, field, value)
    with catch_integrity_errors():
        await db.commit()
    await db.refresh(vlan)
    return vlan


async def delete_vlan(db: AsyncSession, vlan_pk: int) -> None:
    vlan = await get_vlan(db, vlan_pk)
    await db.delete(vlan)
    with catch_integrity_errors():
        # If subnets or ports reference this VLAN, ON DELETE SET NULL kicks in.
        # That is not actually an integrity error, but listing here for completeness.
        await db.commit()
