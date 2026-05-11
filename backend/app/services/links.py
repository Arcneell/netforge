"""Links service.

The DB CHECK constraint requires `port_a_id < port_b_id` so that each
edge is canonical. The service swaps the two values if the caller
provided them in the other order — the API stays user-friendly while
the DB stays clean.
"""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.link import Link
from app.models.port import Port
from app.schemas.common import PageParams
from app.schemas.link import LinkCreate
from app.services.errors import catch_integrity_errors, not_found


async def list_links(
    db: AsyncSession,
    page: PageParams,
    switch_id: int | None = None,
) -> tuple[list[Link], int]:
    base = select(Link)
    count_q = select(func.count()).select_from(Link)
    if switch_id is not None:
        # A link belongs to a switch if either of its endpoints does.
        switch_ports = select(Port.id).where(Port.switch_id == switch_id)
        cond = or_(Link.port_a_id.in_(switch_ports), Link.port_b_id.in_(switch_ports))
        base = base.where(cond)
        count_q = count_q.where(cond)

    total = (await db.execute(count_q)).scalar() or 0
    result = await db.execute(
        base.order_by(Link.id).offset(page.offset).limit(page.limit)
    )
    return list(result.scalars().all()), int(total)


async def get_link(db: AsyncSession, link_id: int) -> Link:
    link = await db.get(Link, link_id)
    if link is None:
        not_found("Link", link_id)
    return link


async def create_link(db: AsyncSession, payload: LinkCreate) -> Link:
    data = payload.model_dump()

    # Canonical ordering for the CHECK constraint.
    a, b = data["port_a_id"], data["port_b_id"]
    if a > b:
        data["port_a_id"], data["port_b_id"] = b, a

    # Validate both endpoints actually exist — cleaner 404 than letting
    # the FK violation bubble up.
    for key in ("port_a_id", "port_b_id"):
        port = await db.get(Port, data[key])
        if port is None:
            not_found("Port", data[key])

    link = Link(**data)
    db.add(link)
    with catch_integrity_errors():
        await db.commit()
    await db.refresh(link)
    return link


async def delete_link(db: AsyncSession, link_id: int) -> None:
    link = await get_link(db, link_id)
    await db.delete(link)
    await db.commit()
