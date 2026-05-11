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

from app.models.device import Device
from app.models.ip import Ip
from app.models.port import Port
from app.models.switch import Switch
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
            )
        )

    return results


def _mac_str(mac: object | None) -> str | None:
    return None if mac is None else str(mac)
