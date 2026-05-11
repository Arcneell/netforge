"""Devices router — /api/devices."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.db import get_session as get_db
from app.models.user import UserRole
from app.schemas.common import Page, PageParams
from app.schemas.device import DeviceCreate, DeviceRead, DeviceType, DeviceUpdate
from app.services import devices as service

router = APIRouter(prefix="/devices", tags=["devices"])


@router.get("", response_model=Page[DeviceRead], dependencies=[Depends(get_current_user)])
async def list_devices(
    page: PageParams = Depends(),
    type_: DeviceType | None = Query(default=None, alias="type"),
    room_id: int | None = Query(default=None, gt=0),
    q: str | None = Query(default=None, min_length=1, max_length=120),
    db: AsyncSession = Depends(get_db),
) -> Page[DeviceRead]:
    items, total = await service.list_devices(db, page, type_=type_, room_id=room_id, q=q)
    return Page[DeviceRead](
        items=[DeviceRead.model_validate(d) for d in items],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get(
    "/{device_id}", response_model=DeviceRead, dependencies=[Depends(get_current_user)]
)
async def get_device(device_id: int, db: AsyncSession = Depends(get_db)) -> DeviceRead:
    device = await service.get_device(db, device_id)
    return DeviceRead.model_validate(device)


@router.post(
    "",
    response_model=DeviceRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def create_device(
    payload: DeviceCreate, db: AsyncSession = Depends(get_db)
) -> DeviceRead:
    device = await service.create_device(db, payload)
    return DeviceRead.model_validate(device)


@router.put(
    "/{device_id}",
    response_model=DeviceRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def update_device(
    device_id: int, payload: DeviceUpdate, db: AsyncSession = Depends(get_db)
) -> DeviceRead:
    device = await service.update_device(db, device_id, payload)
    return DeviceRead.model_validate(device)


@router.delete(
    "/{device_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def delete_device(device_id: int, db: AsyncSession = Depends(get_db)) -> None:
    await service.delete_device(db, device_id)
