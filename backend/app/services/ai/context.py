"""Build the structured snapshot of the network handed to the LLM.

Format choice: compact JSON, not natural-language prose. The model reads
JSON faster, we save tokens, and prompt caching gets the longest possible
identical-byte prefix when we re-run with no infrastructure changes.

Privacy: only the fields useful for the analysis ship — we deliberately
strip notes-style PII columns we'd rather not send to a third-party API.
Easy to relax later if a feature needs them.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import Room, Site
from app.models.device import Device
from app.models.link import Link
from app.models.port import Port
from app.models.switch import Switch
from app.models.vlan import Vlan


async def build_topology_context(db: AsyncSession) -> dict[str, Any]:
    """Compact snapshot of every entity the link-suggestion AI needs."""
    sites = (await db.execute(select(Site))).scalars().all()
    rooms = (await db.execute(select(Room))).scalars().all()
    switches = (await db.execute(select(Switch))).scalars().all()
    ports = (await db.execute(select(Port))).scalars().all()
    devices = (await db.execute(select(Device))).scalars().all()
    links = (await db.execute(select(Link))).scalars().all()
    vlans = (await db.execute(select(Vlan))).scalars().all()

    def _device_name(d_id: int | None) -> str | None:
        if not d_id:
            return None
        for d in devices:
            if d.id == d_id:
                return d.name
        return None

    return {
        "sites": [
            {"id": s.id, "name": s.name, "code": s.code, "address": s.address}
            for s in sites
        ],
        "rooms": [
            {
                "id": r.id,
                "site_id": r.site_id,
                "code": r.code,
                "description": r.description,
            }
            for r in rooms
        ],
        "switches": [
            {
                "id": s.id,
                "name": s.name,
                "vendor": s.vendor,
                "model": s.model,
                "site_id": s.site_id,
                "room_id": s.room_id,
                "description": s.description,
            }
            for s in switches
        ],
        "ports": [
            {
                "id": p.id,
                "switch_id": p.switch_id,
                "number": p.number,
                "label": p.label,
                "mode": p.mode.value if p.mode else None,
                "native_vlan_id": p.native_vlan_id,
                "admin_status": p.admin_status.value if p.admin_status else None,
                "connected_device_id": p.connected_device_id,
                "connected_device_name": _device_name(p.connected_device_id),
                # Notes can hold operator hints like "uplink to SW-CORE-01" —
                # the single most-useful free-text field for linking.
                "notes": p.notes,
            }
            for p in ports
        ],
        "vlans": [
            {"id": v.id, "vlan_id": v.vlan_id, "name": v.name} for v in vlans
        ],
        "existing_links": [
            {"port_a_id": link.port_a_id, "port_b_id": link.port_b_id}
            for link in links
        ],
    }
