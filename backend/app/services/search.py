"""Global search.

Runs one bounded query per entity type, then merges the results client-side.
Less elegant than a UNION ALL with a normalised projection, but avoids the
Postgres-specific gymnastics around heterogeneous column types (inet, macaddr,
text) and stays readable.

Each query is capped at `_PER_TYPE_LIMIT` so a wide match doesn't flood the
response. The router can apply a global cap if needed.
"""

from __future__ import annotations

from sqlalchemy import String, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import Room, Site
from app.models.device import Device
from app.models.ip import Ip
from app.models.port import Port
from app.models.subnet import Subnet
from app.models.switch import Switch
from app.models.vlan import Vlan
from app.schemas.search import SearchResult

_PER_TYPE_LIMIT = 10


async def search(db: AsyncSession, q: str) -> list[SearchResult]:
    pattern = f"%{q}%"
    results: list[SearchResult] = []

    # IPs — match address, hostname, or MAC.
    ip_rows = (
        await db.execute(
            select(Ip)
            .where(
                or_(
                    cast(Ip.address, String).ilike(pattern),
                    Ip.hostname.ilike(pattern),
                    cast(Ip.mac, String).ilike(pattern),
                )
            )
            .limit(_PER_TYPE_LIMIT)
        )
    ).scalars().all()
    for ip in ip_rows:
        context_bits = [b for b in (ip.hostname, _mac_str(ip.mac)) if b]
        results.append(
            SearchResult(
                type="ip",
                id=ip.id,
                label=str(ip.address),
                context=" / ".join(context_bits) if context_bits else None,
                parent_id=ip.subnet_id,
            )
        )

    # Devices — match name, serial, model.
    device_rows = (
        await db.execute(
            select(Device)
            .where(
                or_(
                    Device.name.ilike(pattern),
                    Device.serial.ilike(pattern),
                    Device.model.ilike(pattern),
                )
            )
            .limit(_PER_TYPE_LIMIT)
        )
    ).scalars().all()
    for dev in device_rows:
        context_bits = [b for b in (dev.vendor, dev.model, dev.serial) if b]
        results.append(
            SearchResult(
                type="device",
                id=dev.id,
                label=dev.name,
                context=" / ".join(context_bits) if context_bits else None,
            )
        )

    # Switches — match name, management IP.
    switch_rows = (
        await db.execute(
            select(Switch)
            .where(
                or_(
                    Switch.name.ilike(pattern),
                    cast(Switch.management_ip, String).ilike(pattern),
                )
            )
            .limit(_PER_TYPE_LIMIT)
        )
    ).scalars().all()
    for sw in switch_rows:
        context_bits = [b for b in (sw.vendor, sw.model) if b]
        results.append(
            SearchResult(
                type="switch",
                id=sw.id,
                label=sw.name,
                context=" / ".join(context_bits) if context_bits else None,
            )
        )

    # Ports — match the free-form label. We join the switch to build the
    # "SW-X / port N" label so it's actionable in the UI.
    port_rows = (
        await db.execute(
            select(Port, Switch)
            .join(Switch, Port.switch_id == Switch.id)
            .where(Port.label.ilike(pattern))
            .limit(_PER_TYPE_LIMIT)
        )
    ).all()
    for port, sw in port_rows:
        results.append(
            SearchResult(
                type="port",
                id=port.id,
                label=f"{sw.name} / port {port.number}",
                context=port.label,
                parent_id=sw.id,
            )
        )

    # Sites — match code, name, address.
    site_rows = (
        await db.execute(
            select(Site)
            .where(
                or_(
                    Site.code.ilike(pattern),
                    Site.name.ilike(pattern),
                    Site.address.ilike(pattern),
                )
            )
            .limit(_PER_TYPE_LIMIT)
        )
    ).scalars().all()
    for site in site_rows:
        results.append(
            SearchResult(
                type="site",
                id=site.id,
                label=site.code,
                context=site.name,
            )
        )

    # Rooms — match code or description; qualify the label with the site code
    # so "SALLE-SRV-01" is unambiguous when several sites share room codes.
    room_rows = (
        await db.execute(
            select(Room, Site.code)
            .join(Site, Room.site_id == Site.id)
            .where(
                or_(
                    Room.code.ilike(pattern),
                    Room.description.ilike(pattern),
                )
            )
            .limit(_PER_TYPE_LIMIT)
        )
    ).all()
    for room, site_code in room_rows:
        results.append(
            SearchResult(
                type="room",
                id=room.id,
                label=f"{site_code} / {room.code}",
                context=room.description,
            )
        )

    # VLANs — match the public numeric id (cast to text so the same `pattern`
    # works for "10" and "VLAN-VOIP"), name, description.
    vlan_rows = (
        await db.execute(
            select(Vlan)
            .where(
                or_(
                    cast(Vlan.vlan_id, String).ilike(pattern),
                    Vlan.name.ilike(pattern),
                    Vlan.description.ilike(pattern),
                )
            )
            .limit(_PER_TYPE_LIMIT)
        )
    ).scalars().all()
    for vlan in vlan_rows:
        results.append(
            SearchResult(
                type="vlan",
                # NB: `id` is the DB primary key (used by the frontend router);
                # the user-facing 802.1Q id goes in the label.
                id=vlan.id,
                label=f"VLAN {vlan.vlan_id} — {vlan.name}",
                context=vlan.description,
            )
        )

    # Subnets — match CIDR (cast to text) or description.
    subnet_rows = (
        await db.execute(
            select(Subnet, Site.code)
            .outerjoin(Site, Subnet.site_id == Site.id)
            .where(
                or_(
                    cast(Subnet.cidr, String).ilike(pattern),
                    Subnet.description.ilike(pattern),
                )
            )
            .limit(_PER_TYPE_LIMIT)
        )
    ).all()
    for subnet, site_code in subnet_rows:
        context_bits = [b for b in (site_code, subnet.description) if b]
        results.append(
            SearchResult(
                type="subnet",
                id=subnet.id,
                label=str(subnet.cidr),
                context=" / ".join(context_bits) if context_bits else None,
            )
        )

    return results


def _mac_str(mac: object | None) -> str | None:
    return None if mac is None else str(mac)
