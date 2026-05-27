"""Ports service.

Ports are created automatically with their switch — no POST endpoint, no
DELETE endpoint. Only PUT (update editable fields) and the tagged-VLAN
add/remove operations.
"""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.port import Port, PortVlan
from app.models.vlan import Vlan
from app.schemas.common import PageParams
from app.schemas.port import PortUpdate
from app.services.errors import (
    business_rule,
    catch_integrity_errors,
    conflict,
    not_found,
)


async def list_ports_of_switch(
    db: AsyncSession, switch_id: int, page: PageParams
) -> tuple[list[Port], int]:
    total = (
        await db.execute(
            select(func.count()).select_from(Port).where(Port.switch_id == switch_id)
        )
    ).scalar() or 0
    result = await db.execute(
        select(Port)
        .where(Port.switch_id == switch_id)
        .order_by(Port.number)
        .offset(page.offset)
        .limit(page.limit)
    )
    return list(result.scalars().all()), int(total)


async def get_port(db: AsyncSession, port_id: int) -> Port:
    port = await db.get(Port, port_id)
    if port is None:
        not_found("Port", port_id)
    return port


async def list_tagged_vlans(db: AsyncSession, port_id: int) -> list[Vlan]:
    """Return every VLAN tagged on the given trunk port.

    The PortEditor UI needs this to populate its tagged-VLAN list on open;
    without it the modal had to reset to empty on every reopen and silently
    drop the user's prior view of the set. 404 on the parent port matches
    the rest of the `/api/ports/{port_id}/...` surface.
    """
    await get_port(db, port_id)
    rows = await db.execute(
        select(Vlan)
        .join(PortVlan, PortVlan.vlan_id == Vlan.id)
        .where(PortVlan.port_id == port_id)
        .order_by(Vlan.vlan_id)
    )
    return list(rows.scalars().all())


async def update_port(db: AsyncSession, port_id: int, payload: PortUpdate) -> Port:
    port = await get_port(db, port_id)
    patch = payload.model_dump(exclude_unset=True)
    # Mirror the invariant `add_tagged_vlan` enforces: a port can't have
    # the same VLAN as both native and tagged. Without this guard an
    # admin can PUT a native_vlan_id that is already in the port's
    # tagged set and end up with an inconsistent port that CSV exports,
    # the topology graph, and the AI snapshot all carry downstream.
    new_native = patch.get("native_vlan_id")
    if new_native is not None and new_native != port.native_vlan_id:
        clash = await db.execute(
            select(PortVlan.vlan_id).where(
                PortVlan.port_id == port_id, PortVlan.vlan_id == new_native
            )
        )
        if clash.scalar_one_or_none() is not None:
            business_rule(
                "VLAN_IS_NATIVE",
                "Cannot set the native VLAN to a VLAN already tagged on this port.",
                details={"port_id": port_id, "vlan_id": new_native},
            )
    for field, value in patch.items():
        setattr(port, field, value)
    with catch_integrity_errors():
        await db.commit()
    await db.refresh(port)
    return port


async def add_tagged_vlan(db: AsyncSession, port_id: int, vlan_pk: int) -> None:
    port = await get_port(db, port_id)
    vlan = await db.get(Vlan, vlan_pk)
    if vlan is None:
        not_found("VLAN", vlan_pk)

    # A trunk-tagged VLAN equal to the native VLAN is almost always a config bug.
    if port.native_vlan_id == vlan_pk:
        business_rule(
            "VLAN_IS_NATIVE",
            "Cannot tag the native VLAN as a trunk VLAN on the same port.",
            details={"port_id": port_id, "vlan_id": vlan_pk},
        )

    existing = await db.execute(
        select(PortVlan).where(
            PortVlan.port_id == port_id, PortVlan.vlan_id == vlan_pk
        )
    )
    if existing.scalar_one_or_none() is not None:
        conflict(
            "VLAN_ALREADY_TAGGED",
            "This VLAN is already tagged on this port.",
            details={"port_id": port_id, "vlan_id": vlan_pk},
        )

    db.add(PortVlan(port_id=port_id, vlan_id=vlan_pk))
    with catch_integrity_errors():
        await db.commit()


async def remove_tagged_vlan(db: AsyncSession, port_id: int, vlan_pk: int) -> None:
    # 404 on the parent port keeps the URL coherent if the port was deleted.
    await get_port(db, port_id)
    result = await db.execute(
        delete(PortVlan).where(
            PortVlan.port_id == port_id, PortVlan.vlan_id == vlan_pk
        )
    )
    if result.rowcount == 0:
        not_found("Tagged VLAN", f"{port_id}/{vlan_pk}")
    await db.commit()
