"""Links router — /api/links."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.db import get_session as get_db
from app.models.user import UserRole
from app.schemas.common import Page, PageParams
from app.schemas.link import LinkCreate, LinkCreateByName, LinkRead, LinkUpdate
from app.services import links as service

router = APIRouter(prefix="/links", tags=["links"])


@router.get("", response_model=Page[LinkRead], dependencies=[Depends(get_current_user)])
async def list_links(
    page: PageParams = Depends(),
    switch_id: int | None = Query(default=None, gt=0),
    db: AsyncSession = Depends(get_db),
) -> Page[LinkRead]:
    items, total = await service.list_links(db, page, switch_id=switch_id)
    return Page[LinkRead](
        items=[LinkRead.model_validate(link) for link in items],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


# `/by-name` must be declared before the catch-all `/{link_id}` route below,
# otherwise FastAPI would route it to `get_link` and fail to parse "by-name"
# as an int.
@router.post(
    "/by-name",
    response_model=LinkRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def create_link_by_name(
    payload: LinkCreateByName, db: AsyncSession = Depends(get_db)
) -> LinkRead:
    """Same as POST /api/links but addresses ports by (switch_name, number)
    instead of numeric ids. Convenience path for the topology editor UI."""
    link = await service.create_link_by_name(db, payload)
    return LinkRead.model_validate(link)


@router.get(
    "/{link_id}", response_model=LinkRead, dependencies=[Depends(get_current_user)]
)
async def get_link(link_id: int, db: AsyncSession = Depends(get_db)) -> LinkRead:
    link = await service.get_link(db, link_id)
    return LinkRead.model_validate(link)


@router.post(
    "",
    response_model=LinkRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def create_link(
    payload: LinkCreate, db: AsyncSession = Depends(get_db)
) -> LinkRead:
    link = await service.create_link(db, payload)
    return LinkRead.model_validate(link)


@router.put(
    "/{link_id}",
    response_model=LinkRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def update_link(
    link_id: int, payload: LinkUpdate, db: AsyncSession = Depends(get_db)
) -> LinkRead:
    """Patch link metadata (type, speed, description). Endpoints are
    immutable — to change the connected ports, delete and recreate."""
    link = await service.update_link(db, link_id, payload)
    return LinkRead.model_validate(link)


@router.delete(
    "/{link_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def delete_link(link_id: int, db: AsyncSession = Depends(get_db)) -> None:
    await service.delete_link(db, link_id)
