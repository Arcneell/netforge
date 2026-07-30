"""Links service.

The DB CHECK constraint requires `port_a_id < port_b_id` so that each
edge is canonical. The service swaps the two values if the caller
provided them in the other order — the API stays user-friendly while
the DB stays clean.
"""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.link import Link
from app.models.port import Port
from app.models.switch import Switch
from app.schemas.common import PageParams
from app.schemas.link import LinkCreate, LinkCreateByName, LinkUpdate
from app.services.errors import business_rule, catch_integrity_errors, not_found


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

    # Refuse to create a second link for a port that's already an endpoint
    # of another one. The DB has `UniqueConstraint(port_a_id, port_b_id)`
    # but that only rejects the exact same pair reinserted — a physical
    # port can only realise one cable, so the AI suggest-links accept path
    # AND any direct POST /api/links must surface this clash explicitly
    # instead of producing a non-physical topology.
    #
    # This SELECT runs outside any lock, so it's a fast, friendly check —
    # not the authority. Two concurrent requests wiring the same port to
    # two different peers can both pass it before either commits. The
    # `links_validate_port_exclusivity` trigger (migration 0022) is what
    # actually closes that race at the DB level; its violation is caught
    # below and mapped to the same 400 this pre-check returns.
    existing = await db.execute(
        select(Link.id, Link.port_a_id, Link.port_b_id).where(
            or_(
                Link.port_a_id.in_([data["port_a_id"], data["port_b_id"]]),
                Link.port_b_id.in_([data["port_a_id"], data["port_b_id"]]),
            )
        )
    )
    for row in existing.all():
        if row.id is None:
            continue
        # Same pair, canonical order — leave the integrity layer to
        # surface that as DUPLICATE_LINK (it already maps the unique
        # constraint to a clean 409).
        if row.port_a_id == data["port_a_id"] and row.port_b_id == data["port_b_id"]:
            continue
        business_rule(
            "PORT_ALREADY_LINKED",
            "One or both ports are already an endpoint of another link.",
            details={
                "existing_link_id": int(row.id),
                "port_a_id": data["port_a_id"],
                "port_b_id": data["port_b_id"],
            },
        )

    link = Link(**data)
    db.add(link)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        msg = str(getattr(exc, "orig", exc))
        if "links_port_exclusivity" in msg:
            # Closes the TOCTOU race the pre-check above can't: two
            # concurrent requests can both pass that SELECT before either
            # commits. Same code/message as the non-racing case above, so
            # the caller can't tell which path caught it.
            business_rule(
                "PORT_ALREADY_LINKED",
                "One or both ports are already an endpoint of another link.",
            )
        # Anything else (e.g. the exact-pair `links_ports_uniq` duplicate)
        # goes through the shared mapping for a stable 409.
        with catch_integrity_errors():
            raise
    await db.refresh(link)
    return link


async def create_link_by_name(db: AsyncSession, payload: LinkCreateByName) -> Link:
    """Resolve (switch name, port number) → port ids, then delegate.

    Cleaner 404s than letting a downstream FK violation bubble up, and the
    error surfaces *which* end the caller got wrong (rather than a generic
    "port not found").
    """
    pa = await _port_by_switch_and_number(db, payload.switch_a, payload.port_a)
    pb = await _port_by_switch_and_number(db, payload.switch_b, payload.port_b)

    return await create_link(
        db,
        LinkCreate(
            port_a_id=pa.id,
            port_b_id=pb.id,
            link_type=payload.link_type,
            speed_mbps=payload.speed_mbps,
            description=payload.description,
        ),
    )


async def update_link(db: AsyncSession, link_id: int, payload: LinkUpdate) -> Link:
    """Patch the link's metadata in place. Endpoints are intentionally not
    editable here — to move a link, delete and recreate."""
    link = await get_link(db, link_id)

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(link, field, value)

    with catch_integrity_errors():
        await db.commit()
    await db.refresh(link)
    return link


async def delete_link(db: AsyncSession, link_id: int) -> None:
    link = await get_link(db, link_id)
    await db.delete(link)
    await db.commit()


async def _port_by_switch_and_number(
    db: AsyncSession, switch_name: str, port_number: int
) -> Port:
    """Look up the port identified by its switch name + 1-based port number.
    Raises 404 with a message that names which side failed so the UI can
    point the user at the right field."""
    switch_row = await db.execute(select(Switch).where(Switch.name == switch_name))
    switch = switch_row.scalar_one_or_none()
    if switch is None:
        not_found("Switch", switch_name)

    port_row = await db.execute(
        select(Port).where(Port.switch_id == switch.id, Port.number == port_number)
    )
    port = port_row.scalar_one_or_none()
    if port is None:
        not_found("Port", f"{switch_name}:{port_number}")
    return port
