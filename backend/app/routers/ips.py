"""IPs router — /api/ips."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.db import get_session as get_db
from app.models.user import UserRole
from app.schemas.common import Page, PageParams
from app.schemas.ip import IpCreate, IpRead, IpStatus, IpUpdate
from app.services import ips as service

router = APIRouter(prefix="/ips", tags=["ips"])


@router.get("", response_model=Page[IpRead], dependencies=[Depends(get_current_user)])
async def list_ips(
    page: PageParams = Depends(),
    subnet_id: int | None = Query(default=None, gt=0),
    status_filter: IpStatus | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, min_length=1, max_length=120),
    db: AsyncSession = Depends(get_db),
) -> Page[IpRead]:
    items, total = await service.list_ips(
        db, page, subnet_id=subnet_id, status=status_filter, q=q
    )
    return Page[IpRead](
        items=[IpRead.model_validate(i) for i in items],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get("/{ip_id}", response_model=IpRead, dependencies=[Depends(get_current_user)])
async def get_ip(ip_id: int, db: AsyncSession = Depends(get_db)) -> IpRead:
    ip = await service.get_ip(db, ip_id)
    return IpRead.model_validate(ip)


@router.post(
    "",
    response_model=IpRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def create_ip(
    payload: IpCreate, db: AsyncSession = Depends(get_db)
) -> IpRead:
    ip = await service.create_ip(db, payload)
    return IpRead.model_validate(ip)


@router.put(
    "/{ip_id}",
    response_model=IpRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def update_ip(
    ip_id: int, payload: IpUpdate, db: AsyncSession = Depends(get_db)
) -> IpRead:
    ip = await service.update_ip(db, ip_id, payload)
    return IpRead.model_validate(ip)


@router.delete(
    "/{ip_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def delete_ip(ip_id: int, db: AsyncSession = Depends(get_db)) -> None:
    await service.delete_ip(db, ip_id)
