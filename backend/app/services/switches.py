"""Switches service.

Creating a switch atomically creates its N ports, all in `mode='access'`
and `admin_status='up'`. The unit of work is a single commit — if the
constraint fires (duplicate name), nothing is left behind.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.port import Port, PortAdminStatus, PortMode
from app.models.switch import Switch
from app.schemas.common import PageParams
from app.schemas.switch import SwitchCreate, SwitchUpdate
from app.services.errors import catch_integrity_errors, not_found


async def list_switches(
    db: AsyncSession,
    page: PageParams,
    room_id: int | None = None,
) -> tuple[list[Switch], int]:
    base = select(Switch)
    count_q = select(func.count()).select_from(Switch)
    if room_id is not None:
        base = base.where(Switch.room_id == room_id)
        count_q = count_q.where(Switch.room_id == room_id)

    total = (await db.execute(count_q)).scalar() or 0
    result = await db.execute(
        base.order_by(Switch.name).offset(page.offset).limit(page.limit)
    )
    return list(result.scalars().all()), int(total)


async def get_switch(db: AsyncSession, switch_id: int) -> Switch:
    switch = await db.get(Switch, switch_id)
    if switch is None:
        not_found("Switch", switch_id)
    return switch


async def create_switch(db: AsyncSession, payload: SwitchCreate) -> Switch:
    switch = Switch(**payload.model_dump())

    # Auto-generate the N ports. They get attached via the `ports` relationship,
    # so SQLAlchemy will INSERT them in the same flush as the switch.
    for n in range(1, payload.port_count + 1):
        switch.ports.append(
            Port(
                number=n,
                mode=PortMode.access,
                admin_status=PortAdminStatus.up,
            )
        )

    db.add(switch)
    with catch_integrity_errors():
        await db.commit()
    await db.refresh(switch)
    return switch


async def update_switch(
    db: AsyncSession, switch_id: int, payload: SwitchUpdate
) -> Switch:
    switch = await get_switch(db, switch_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(switch, field, value)
    with catch_integrity_errors():
        await db.commit()
    await db.refresh(switch)
    return switch


async def delete_switch(db: AsyncSession, switch_id: int) -> None:
    switch = await get_switch(db, switch_id)
    # Ports cascade via FK ON DELETE CASCADE; links on those ports cascade too.
    await db.delete(switch)
    with catch_integrity_errors():
        await db.commit()
