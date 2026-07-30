"""Cables router — /api/cables (+ nested /api/links/{id}/cable)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.db import get_session as get_db
from app.models.user import UserRole
from app.schemas.cable import CableCreate, CableRead, CableUpdate
from app.schemas.common import Page, PageParams
from app.services import cables as service
from app.services.errors import not_found

router = APIRouter(prefix="/cables", tags=["cables"])


@router.get("", response_model=Page[CableRead], dependencies=[Depends(get_current_user)])
async def list_cables(
    page: PageParams = Depends(),
    in_stock: bool = Query(default=False, description="Only cables with no link assigned."),
    db: AsyncSession = Depends(get_db),
) -> Page[CableRead]:
    items, total = await service.list_cables(db, page, in_stock_only=in_stock)
    return Page[CableRead](
        items=[CableRead.model_validate(r) for r in items],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get("/{cable_id}", response_model=CableRead, dependencies=[Depends(get_current_user)])
async def get_cable(cable_id: int, db: AsyncSession = Depends(get_db)) -> CableRead:
    row = await service.get_cable(db, cable_id)
    return CableRead.model_validate(row)


@router.post(
    "",
    response_model=CableRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def create_cable(
    payload: CableCreate, db: AsyncSession = Depends(get_db)
) -> CableRead:
    row = await service.create_cable(db, payload)
    return CableRead.model_validate(row)


@router.put(
    "/{cable_id}",
    response_model=CableRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def update_cable(
    cable_id: int, payload: CableUpdate, db: AsyncSession = Depends(get_db)
) -> CableRead:
    row = await service.update_cable(db, cable_id, payload)
    return CableRead.model_validate(row)


@router.delete(
    "/{cable_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def delete_cable(cable_id: int, db: AsyncSession = Depends(get_db)) -> None:
    await service.delete_cable(db, cable_id)


# --- Nested under /api/links/{id}/cable — convenience accessor ---------------

nested_router = APIRouter(prefix="/links", tags=["cables"])


@nested_router.get(
    "/{link_id}/cable",
    response_model=CableRead,
    dependencies=[Depends(get_current_user)],
)
async def get_link_cable(
    link_id: int, db: AsyncSession = Depends(get_db)
) -> CableRead:
    """Returns the cable attached to a given link. 404 when the link has no
    cable metadata yet — the UI uses this to switch between create / edit."""
    row = await service.get_cable_for_link(db, link_id)
    if row is None:
        not_found("Cable for link", link_id)
    return CableRead.model_validate(row)
