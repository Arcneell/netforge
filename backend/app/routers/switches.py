"""Switches router — /api/switches."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.db import get_session as get_db
from app.models.user import UserRole
from app.schemas.common import Page, PageParams
from app.schemas.switch import SwitchCreate, SwitchRead, SwitchUpdate
from app.services import switches as service

router = APIRouter(prefix="/switches", tags=["switches"])


@router.get(
    "", response_model=Page[SwitchRead], dependencies=[Depends(get_current_user)]
)
async def list_switches(
    page: PageParams = Depends(),
    room_id: int | None = Query(default=None, gt=0),
    db: AsyncSession = Depends(get_db),
) -> Page[SwitchRead]:
    items, total = await service.list_switches(db, page, room_id=room_id)
    return Page[SwitchRead](
        items=[SwitchRead.model_validate(s) for s in items],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get(
    "/{switch_id}", response_model=SwitchRead, dependencies=[Depends(get_current_user)]
)
async def get_switch(switch_id: int, db: AsyncSession = Depends(get_db)) -> SwitchRead:
    switch = await service.get_switch(db, switch_id)
    return SwitchRead.model_validate(switch)


@router.post(
    "",
    response_model=SwitchRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def create_switch(
    payload: SwitchCreate, db: AsyncSession = Depends(get_db)
) -> SwitchRead:
    switch = await service.create_switch(db, payload)
    return SwitchRead.model_validate(switch)


@router.put(
    "/{switch_id}",
    response_model=SwitchRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def update_switch(
    switch_id: int, payload: SwitchUpdate, db: AsyncSession = Depends(get_db)
) -> SwitchRead:
    switch = await service.update_switch(db, switch_id, payload)
    return SwitchRead.model_validate(switch)


@router.delete(
    "/{switch_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def delete_switch(switch_id: int, db: AsyncSession = Depends(get_db)) -> None:
    await service.delete_switch(db, switch_id)
