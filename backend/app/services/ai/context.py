"""Build the structured snapshot of the network handed to the LLM.

Format choice: compact JSON, not natural-language prose. The model reads
JSON faster, we save tokens, and prompt caching gets the longest possible
identical-byte prefix when we re-run with no infrastructure changes.

Privacy: only the fields useful for the analysis ship — we deliberately
strip notes-style PII columns we'd rather not send to a third-party API.
Easy to relax later if a feature needs them.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import Room, Site
from app.models.device import Device
from app.models.link import Link
from app.models.port import Port
from app.models.subnet import Subnet
from app.models.switch import Switch
from app.models.vlan import Vlan

# Patterns that look like prompt-injection attempts inside free-text fields
# (port notes, descriptions). Admins type those fields, but a CSV import or a
# previous compromise might have introduced something hostile. We blank the
# field rather than fight a parsing arms-race — the legitimate use case is
# "uplink to SW-CORE-01 port 24", not "Disregard previous instructions".
_INJECTION_HINT_RE = re.compile(
    r"(ignore\s+(all\s+)?previous|disregard\s+previous|"
    r"system\s+prompt|forget\s+(all\s+)?(your\s+)?instructions|"
    r"you\s+are\s+now\s+|new\s+instructions:|"
    r"<\s*\|.*\|\s*>|"
    r"```\s*system|"
    r"\[\s*system\s*\])",
    re.IGNORECASE | re.DOTALL,
)
# Cap any single free-text field — paste-bombing a 50 KB README into a port
# note would otherwise show up in the prompt verbatim.
_FREE_TEXT_MAX = 500


def _sanitize_freetext(value: str | None) -> str | None:
    """Strip control chars, length-cap, and replace likely prompt-injection
    payloads with a fixed marker. Returns None unchanged."""
    if value is None:
        return None
    cleaned = "".join(ch for ch in value if ch == "\n" or ch == "\t" or ord(ch) >= 0x20)
    if len(cleaned) > _FREE_TEXT_MAX:
        cleaned = cleaned[:_FREE_TEXT_MAX] + "…"
    if _INJECTION_HINT_RE.search(cleaned):
        return "[redacted: suspicious content]"
    return cleaned


async def build_topology_context(db: AsyncSession) -> dict[str, Any]:
    """Compact snapshot of every entity the AI features (suggest_links,
    advisor, nl_query) need."""
    sites = (await db.execute(select(Site))).scalars().all()
    rooms = (await db.execute(select(Room))).scalars().all()
    switches = (await db.execute(select(Switch))).scalars().all()
    ports = (await db.execute(select(Port))).scalars().all()
    devices = (await db.execute(select(Device))).scalars().all()
    links = (await db.execute(select(Link))).scalars().all()
    vlans = (await db.execute(select(Vlan))).scalars().all()
    subnets = (await db.execute(select(Subnet))).scalars().all()

    # Switch → site_id is derived via the room. Build the lookup once so the
    # AI gets a denormalised view (much easier to reason about than chained
    # joins).
    room_to_site = {r.id: r.site_id for r in rooms}
    devices_by_id = {d.id: d for d in devices}

    return {
        "sites": [
            {
                "id": s.id,
                "name": s.name,
                "code": s.code,
                "address": _sanitize_freetext(s.address),
            }
            for s in sites
        ],
        "rooms": [
            {
                "id": r.id,
                "site_id": r.site_id,
                "code": r.code,
                "description": _sanitize_freetext(r.description),
            }
            for r in rooms
        ],
        "switches": [
            {
                "id": s.id,
                "name": s.name,
                "vendor": s.vendor,
                "model": s.model,
                "room_id": s.room_id,
                # Derived for convenience; not a column on switches.
                "site_id": room_to_site.get(s.room_id) if s.room_id else None,
                "port_count": s.port_count,
                "description": _sanitize_freetext(s.description),
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
                "connected_device_name": (
                    devices_by_id[p.connected_device_id].name
                    if p.connected_device_id in devices_by_id
                    else None
                ),
                # Notes can hold operator hints like "uplink to SW-CORE-01" —
                # the single most-useful free-text field for linking.
                "notes": _sanitize_freetext(p.notes),
            }
            for p in ports
        ],
        "vlans": [
            {"id": v.id, "vlan_id": v.vlan_id, "name": v.name} for v in vlans
        ],
        "subnets": [
            {
                "id": s.id,
                # Pydantic Postgres CIDR/INET fields round-trip as IPvNNetwork
                # instances; force str() so json.dumps doesn't blow up later.
                "cidr": str(s.cidr),
                "gateway": str(s.gateway) if s.gateway else None,
                "vlan_id": s.vlan_id,
                "site_id": s.site_id,
                "dhcp_enabled": s.dhcp_enabled,
                "description": _sanitize_freetext(s.description),
            }
            for s in subnets
        ],
        "existing_links": [
            {"port_a_id": link.port_a_id, "port_b_id": link.port_b_id}
            for link in links
        ],
    }
