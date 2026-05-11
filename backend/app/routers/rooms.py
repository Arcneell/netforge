"""Rooms router — /api/rooms."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.db import get_session as get_db
from app.models.user import UserRole
from app.schemas.common import Page, PageParams
from app.schemas.room import RoomCreate, RoomRead, RoomUpdate
from app.services import rooms as service

router = APIRouter(prefix="/rooms", tags=["rooms"])


@router.get("", response_model=Page[RoomRead], dependencies=[Depends(get_current_user)])
async def list_rooms(
    page: PageParams = Depends(),
    site_id: int | None = Query(default=None, gt=0),
    db: AsyncSession = Depends(get_db),
) -> Page[RoomRead]:
    items, total = await service.list_rooms(db, page, site_id=site_id)
    return Page[RoomRead](
        items=[RoomRead.model_validate(r) for r in items],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get("/{room_id}", response_model=RoomRead, dependencies=[Depends(get_current_user)])
async def get_room(room_id: int, db: AsyncSession = Depends(get_db)) -> RoomRead:
    room = await service.get_room(db, room_id)
    return RoomRead.model_validate(room)


@router.post(
    "",
    response_model=RoomRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def create_room(
    payload: RoomCreate, db: AsyncSession = Depends(get_db)
) -> RoomRead:
    room = await service.create_room(db, payload)
    return RoomRead.model_validate(room)


@router.put(
    "/{room_id}",
    response_model=RoomRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def update_room(
    room_id: int, payload: RoomUpdate, db: AsyncSession = Depends(get_db)
) -> RoomRead:
    room = await service.update_room(db, room_id, payload)
    return RoomRead.model_validate(room)


@router.delete(
    "/{room_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def delete_room(room_id: int, db: AsyncSession = Depends(get_db)) -> None:
    await service.delete_room(db, room_id)
