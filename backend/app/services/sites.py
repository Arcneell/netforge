"""Sites service — CRUD with constraint mapping."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import Site
from app.schemas.common import PageParams
from app.schemas.site import SiteCreate, SiteUpdate
from app.services.errors import catch_integrity_errors, not_found


async def list_sites(db: AsyncSession, page: PageParams) -> tuple[list[Site], int]:
    total = (await db.execute(select(func.count()).select_from(Site))).scalar() or 0
    result = await db.execute(
        select(Site).order_by(Site.id).offset(page.offset).limit(page.limit)
    )
    return list(result.scalars().all()), int(total)


async def get_site(db: AsyncSession, site_id: int) -> Site:
    site = await db.get(Site, site_id)
    if site is None:
        not_found("Site", site_id)
    return site


async def create_site(db: AsyncSession, payload: SiteCreate) -> Site:
    site = Site(**payload.model_dump())
    db.add(site)
    with catch_integrity_errors():
        await db.commit()
    await db.refresh(site)
    return site


async def update_site(db: AsyncSession, site_id: int, payload: SiteUpdate) -> Site:
    site = await get_site(db, site_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(site, field, value)
    with catch_integrity_errors():
        await db.commit()
    await db.refresh(site)
    return site


async def delete_site(db: AsyncSession, site_id: int) -> None:
    site = await get_site(db, site_id)
    await db.delete(site)
    with catch_integrity_errors():
        # FK ON DELETE RESTRICT on rooms / subnets — IntegrityError → 409.
        await db.commit()
