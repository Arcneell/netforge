"""Sites router — /api/sites."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.db import get_session as get_db
from app.models.user import UserRole
from app.schemas.common import Page, PageParams
from app.schemas.site import SiteCreate, SiteRead, SiteUpdate
from app.services import sites as service

router = APIRouter(prefix="/sites", tags=["sites"])


@router.get("", response_model=Page[SiteRead], dependencies=[Depends(get_current_user)])
async def list_sites(
    page: PageParams = Depends(),
    db: AsyncSession = Depends(get_db),
) -> Page[SiteRead]:
    items, total = await service.list_sites(db, page)
    return Page[SiteRead](
        items=[SiteRead.model_validate(s) for s in items],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get("/{site_id}", response_model=SiteRead, dependencies=[Depends(get_current_user)])
async def get_site(site_id: int, db: AsyncSession = Depends(get_db)) -> SiteRead:
    site = await service.get_site(db, site_id)
    return SiteRead.model_validate(site)


@router.post(
    "",
    response_model=SiteRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def create_site(
    payload: SiteCreate, db: AsyncSession = Depends(get_db)
) -> SiteRead:
    site = await service.create_site(db, payload)
    return SiteRead.model_validate(site)


@router.put(
    "/{site_id}",
    response_model=SiteRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def update_site(
    site_id: int, payload: SiteUpdate, db: AsyncSession = Depends(get_db)
) -> SiteRead:
    site = await service.update_site(db, site_id, payload)
    return SiteRead.model_validate(site)


@router.delete(
    "/{site_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def delete_site(site_id: int, db: AsyncSession = Depends(get_db)) -> None:
    await service.delete_site(db, site_id)
