"""VRFs router — /api/vrfs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.db import get_session as get_db
from app.models.user import UserRole
from app.schemas.common import Page, PageParams
from app.schemas.vrf import VrfCreate, VrfRead, VrfUpdate
from app.services import vrfs as service

router = APIRouter(prefix="/vrfs", tags=["vrfs"])


@router.get("", response_model=Page[VrfRead], dependencies=[Depends(get_current_user)])
async def list_vrfs(
    page: PageParams = Depends(), db: AsyncSession = Depends(get_db)
) -> Page[VrfRead]:
    items, total = await service.list_vrfs(db, page)
    return Page[VrfRead](
        items=[VrfRead.model_validate(r) for r in items],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get(
    "/{vrf_id}",
    response_model=VrfRead,
    dependencies=[Depends(get_current_user)],
)
async def get_vrf(vrf_id: int, db: AsyncSession = Depends(get_db)) -> VrfRead:
    row = await service.get_vrf(db, vrf_id)
    return VrfRead.model_validate(row)


@router.post(
    "",
    response_model=VrfRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def create_vrf(
    payload: VrfCreate, db: AsyncSession = Depends(get_db)
) -> VrfRead:
    row = await service.create_vrf(db, payload)
    return VrfRead.model_validate(row)


@router.put(
    "/{vrf_id}",
    response_model=VrfRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def update_vrf(
    vrf_id: int, payload: VrfUpdate, db: AsyncSession = Depends(get_db)
) -> VrfRead:
    row = await service.update_vrf(db, vrf_id, payload)
    return VrfRead.model_validate(row)


@router.delete(
    "/{vrf_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def delete_vrf(vrf_id: int, db: AsyncSession = Depends(get_db)) -> None:
    await service.delete_vrf(db, vrf_id)
