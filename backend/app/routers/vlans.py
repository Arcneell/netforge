"""VLANs router — /api/vlans."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.db import get_session as get_db
from app.models.user import UserRole
from app.schemas.common import Page, PageParams
from app.schemas.vlan import VlanCreate, VlanRead, VlanUpdate
from app.services import vlans as service

router = APIRouter(prefix="/vlans", tags=["vlans"])


@router.get("", response_model=Page[VlanRead], dependencies=[Depends(get_current_user)])
async def list_vlans(
    page: PageParams = Depends(),
    db: AsyncSession = Depends(get_db),
) -> Page[VlanRead]:
    items, total = await service.list_vlans(db, page)
    return Page[VlanRead](
        items=[VlanRead.model_validate(v) for v in items],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get("/{vlan_pk}", response_model=VlanRead, dependencies=[Depends(get_current_user)])
async def get_vlan(vlan_pk: int, db: AsyncSession = Depends(get_db)) -> VlanRead:
    vlan = await service.get_vlan(db, vlan_pk)
    return VlanRead.model_validate(vlan)


@router.post(
    "",
    response_model=VlanRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def create_vlan(
    payload: VlanCreate, db: AsyncSession = Depends(get_db)
) -> VlanRead:
    vlan = await service.create_vlan(db, payload)
    return VlanRead.model_validate(vlan)


@router.put(
    "/{vlan_pk}",
    response_model=VlanRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def update_vlan(
    vlan_pk: int, payload: VlanUpdate, db: AsyncSession = Depends(get_db)
) -> VlanRead:
    vlan = await service.update_vlan(db, vlan_pk, payload)
    return VlanRead.model_validate(vlan)


@router.delete(
    "/{vlan_pk}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def delete_vlan(vlan_pk: int, db: AsyncSession = Depends(get_db)) -> None:
    await service.delete_vlan(db, vlan_pk)
