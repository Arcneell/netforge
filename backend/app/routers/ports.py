"""Ports router — split across /api/switches/{id}/ports and /api/ports."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.db import get_session as get_db
from app.models.user import UserRole
from app.schemas.common import Page, PageParams
from app.schemas.port import PortRead, PortUpdate, TaggedVlanAdd
from app.services import ports as service

# /api/switches/{switch_id}/ports — listing only
nested_router = APIRouter(prefix="/switches", tags=["ports"])


@nested_router.get(
    "/{switch_id}/ports",
    response_model=Page[PortRead],
    dependencies=[Depends(get_current_user)],
)
async def list_ports_of_switch(
    switch_id: int,
    page: PageParams = Depends(),
    db: AsyncSession = Depends(get_db),
) -> Page[PortRead]:
    items, total = await service.list_ports_of_switch(db, switch_id, page)
    return Page[PortRead](
        items=[PortRead.model_validate(p) for p in items],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


# /api/ports/{port_id}  — detail, update, tagged-VLAN management
router = APIRouter(prefix="/ports", tags=["ports"])


@router.get(
    "/{port_id}", response_model=PortRead, dependencies=[Depends(get_current_user)]
)
async def get_port(port_id: int, db: AsyncSession = Depends(get_db)) -> PortRead:
    port = await service.get_port(db, port_id)
    return PortRead.model_validate(port)


@router.put(
    "/{port_id}",
    response_model=PortRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def update_port(
    port_id: int, payload: PortUpdate, db: AsyncSession = Depends(get_db)
) -> PortRead:
    port = await service.update_port(db, port_id, payload)
    return PortRead.model_validate(port)


@router.post(
    "/{port_id}/vlans",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def add_tagged_vlan(
    port_id: int,
    payload: TaggedVlanAdd,
    db: AsyncSession = Depends(get_db),
) -> None:
    await service.add_tagged_vlan(db, port_id, payload.vlan_id)


@router.delete(
    "/{port_id}/vlans/{vlan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def remove_tagged_vlan(
    port_id: int, vlan_id: int, db: AsyncSession = Depends(get_db)
) -> None:
    await service.remove_tagged_vlan(db, port_id, vlan_id)
