"""Subnets router — /api/subnets."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.db import get_session as get_db
from app.models.user import UserRole
from app.schemas.common import Page, PageParams
from app.schemas.subnet import (
    NextFreeIpResponse,
    SubnetCreate,
    SubnetIpsResponse,
    SubnetRead,
    SubnetUpdate,
    SubnetUtilization,
)
from app.services import subnets as service

router = APIRouter(prefix="/subnets", tags=["subnets"])


@router.get("", response_model=Page[SubnetRead], dependencies=[Depends(get_current_user)])
async def list_subnets(
    page: PageParams = Depends(),
    site_id: int | None = Query(default=None, gt=0),
    vlan_id: int | None = Query(default=None, gt=0),
    db: AsyncSession = Depends(get_db),
) -> Page[SubnetRead]:
    items, total = await service.list_subnets(db, page, site_id=site_id, vlan_id=vlan_id)
    return Page[SubnetRead](
        items=[SubnetRead.model_validate(s) for s in items],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get(
    "/{subnet_id}", response_model=SubnetRead, dependencies=[Depends(get_current_user)]
)
async def get_subnet(subnet_id: int, db: AsyncSession = Depends(get_db)) -> SubnetRead:
    subnet = await service.get_subnet(db, subnet_id)
    return SubnetRead.model_validate(subnet)


@router.post(
    "",
    response_model=SubnetRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def create_subnet(
    payload: SubnetCreate, db: AsyncSession = Depends(get_db)
) -> SubnetRead:
    subnet = await service.create_subnet(db, payload)
    return SubnetRead.model_validate(subnet)


@router.put(
    "/{subnet_id}",
    response_model=SubnetRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def update_subnet(
    subnet_id: int, payload: SubnetUpdate, db: AsyncSession = Depends(get_db)
) -> SubnetRead:
    subnet = await service.update_subnet(db, subnet_id, payload)
    return SubnetRead.model_validate(subnet)


@router.delete(
    "/{subnet_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def delete_subnet(subnet_id: int, db: AsyncSession = Depends(get_db)) -> None:
    await service.delete_subnet(db, subnet_id)


# --- Phase 4 utility endpoints -----------------------------------------------


@router.get(
    "/{subnet_id}/ips",
    response_model=SubnetIpsResponse,
    dependencies=[Depends(get_current_user)],
)
async def list_subnet_ips(
    subnet_id: int, db: AsyncSession = Depends(get_db)
) -> SubnetIpsResponse:
    subnet, ips = await service.list_subnet_ips(db, subnet_id)
    return SubnetIpsResponse(subnet=SubnetRead.model_validate(subnet), ips=ips)


@router.post(
    "/{subnet_id}/next-free",
    response_model=NextFreeIpResponse,
    dependencies=[Depends(get_current_user)],
)
async def next_free_ip(
    subnet_id: int, db: AsyncSession = Depends(get_db)
) -> NextFreeIpResponse:
    address = await service.next_free_ip(db, subnet_id)
    return NextFreeIpResponse(address=address)


@router.get(
    "/{subnet_id}/utilization",
    response_model=SubnetUtilization,
    dependencies=[Depends(get_current_user)],
)
async def subnet_utilization(
    subnet_id: int, db: AsyncSession = Depends(get_db)
) -> SubnetUtilization:
    """Fill-rate snapshot for one subnet. Two SELECTs, works on any prefix
    length — unlike `/ips`, this endpoint does not enumerate the address
    space, so it stays cheap on `/16`s and larger."""
    subnet, util = await service.compute_utilization(db, subnet_id)
    return SubnetUtilization(subnet_id=subnet.id, cidr=str(subnet.cidr), **util)
