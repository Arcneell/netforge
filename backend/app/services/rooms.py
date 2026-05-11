"""Rooms service."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import Room
from app.schemas.common import PageParams
from app.schemas.room import RoomCreate, RoomUpdate
from app.services.errors import catch_integrity_errors, not_found


async def list_rooms(
    db: AsyncSession,
    page: PageParams,
    site_id: int | None = None,
) -> tuple[list[Room], int]:
    base = select(Room)
    count_q = select(func.count()).select_from(Room)
    if site_id is not None:
        base = base.where(Room.site_id == site_id)
        count_q = count_q.where(Room.site_id == site_id)

    total = (await db.execute(count_q)).scalar() or 0
    result = await db.execute(
        base.order_by(Room.id).offset(page.offset).limit(page.limit)
    )
    return list(result.scalars().all()), int(total)


async def get_room(db: AsyncSession, room_id: int) -> Room:
    room = await db.get(Room, room_id)
    if room is None:
        not_found("Room", room_id)
    return room


async def create_room(db: AsyncSession, payload: RoomCreate) -> Room:
    room = Room(**payload.model_dump())
    db.add(room)
    with catch_integrity_errors():
        await db.commit()
    await db.refresh(room)
    return room


async def update_room(db: AsyncSession, room_id: int, payload: RoomUpdate) -> Room:
    room = await get_room(db, room_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(room, field, value)
    with catch_integrity_errors():
        await db.commit()
    await db.refresh(room)
    return room


async def delete_room(db: AsyncSession, room_id: int) -> None:
    room = await get_room(db, room_id)
    await db.delete(room)
    with catch_integrity_errors():
        await db.commit()
