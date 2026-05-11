"""Devices service."""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import Device
from app.schemas.common import PageParams
from app.schemas.device import DeviceCreate, DeviceType, DeviceUpdate
from app.services.errors import catch_integrity_errors, not_found


async def list_devices(
    db: AsyncSession,
    page: PageParams,
    type_: DeviceType | None = None,
    room_id: int | None = None,
    q: str | None = None,
) -> tuple[list[Device], int]:
    base = select(Device)
    count_q = select(func.count()).select_from(Device)
    if type_ is not None:
        base = base.where(Device.type == type_)
        count_q = count_q.where(Device.type == type_)
    if room_id is not None:
        base = base.where(Device.room_id == room_id)
        count_q = count_q.where(Device.room_id == room_id)
    if q:
        like = f"%{q}%"
        cond = or_(
            Device.name.ilike(like),
            Device.serial.ilike(like),
            Device.model.ilike(like),
        )
        base = base.where(cond)
        count_q = count_q.where(cond)

    total = (await db.execute(count_q)).scalar() or 0
    result = await db.execute(
        base.order_by(Device.name).offset(page.offset).limit(page.limit)
    )
    return list(result.scalars().all()), int(total)


async def get_device(db: AsyncSession, device_id: int) -> Device:
    device = await db.get(Device, device_id)
    if device is None:
        not_found("Device", device_id)
    return device


async def create_device(db: AsyncSession, payload: DeviceCreate) -> Device:
    device = Device(**payload.model_dump())
    db.add(device)
    with catch_integrity_errors():
        await db.commit()
    await db.refresh(device)
    return device


async def update_device(
    db: AsyncSession, device_id: int, payload: DeviceUpdate
) -> Device:
    device = await get_device(db, device_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(device, field, value)
    with catch_integrity_errors():
        await db.commit()
    await db.refresh(device)
    return device


async def delete_device(db: AsyncSession, device_id: int) -> None:
    device = await get_device(db, device_id)
    # IPs and ports that reference this device get NULL'd by the FK ON DELETE SET NULL.
    await db.delete(device)
    with catch_integrity_errors():
        await db.commit()
