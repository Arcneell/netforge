"""Build the structured snapshot of the network handed to the LLM.

Format choice: compact JSON, not natural-language prose. The model reads
JSON faster, we save tokens, and prompt caching gets the longest possible
identical-byte prefix when we re-run with no infrastructure changes.

Privacy: only the fields useful for the analysis ship — we deliberately
strip notes-style PII columns we'd rather not send to a third-party API.
Easy to relax later if a feature needs them.
"""

from __future__ import annotations

import logging
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

logger = logging.getLogger("netforge.ai.context")

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

# Cap the NUMBER of rows serialised per entity type. Without this, a large
# inventory (a few thousand ports is a normal size for a mid-size site) ships
# to the LLM in full — unbounded prompt size, unbounded cost, and past the
# model's effective context window the tail of the list is silently dropped
# with no indication the snapshot was partial. 500 keeps every feature
# (suggest_links, advisor, nl_query) working on real-world topologies while
# giving a predictable worst-case prompt size.
_MAX_ENTITIES_PER_TYPE = 500


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


def _cap_entities(
    label: str, rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], str | None]:
    """Truncate a serialised entity list to `_MAX_ENTITIES_PER_TYPE` rows.

    Returns `(possibly-truncated rows, truncation note or None)`. The note
    (e.g. "ports: 500 of 3200 shown, truncated") is meant to be surfaced back
    in the snapshot so the LLM — and anyone debugging a weird answer — knows
    the data it saw was partial rather than silently reasoning over an
    incomplete inventory as if it were complete.
    """
    total = len(rows)
    if total <= _MAX_ENTITIES_PER_TYPE:
        return rows, None
    logger.warning(
        "ai.context: %s truncated to %d of %d rows (cap=%d)",
        label,
        _MAX_ENTITIES_PER_TYPE,
        total,
        _MAX_ENTITIES_PER_TYPE,
    )
    note = f"{label}: {_MAX_ENTITIES_PER_TYPE} of {total} shown, truncated"
    return rows[:_MAX_ENTITIES_PER_TYPE], note


async def build_topology_context_cached(db: AsyncSession) -> tuple[dict[str, Any], bool]:
    """Cached variant of `build_topology_context`. Returns `(context, was_cached)`.

    The cache (`services.ai.snapshot_cache`) fingerprints the DB cheaply and
    only re-fetches the full inventory when something has actually changed.
    Use this in any AI feature that doesn't *need* a brand-new read every
    call — the only reason to bypass it would be a debug command."""
    # Local import to avoid an import cycle: snapshot_cache wants to live
    # next to context but conceptually depends on the builder below.
    from app.services.ai.snapshot_cache import get_or_build_context

    return await get_or_build_context(db, builder=build_topology_context)


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

    sites_rows = [
        {
            "id": s.id,
            "name": s.name,
            "code": s.code,
            "address": _sanitize_freetext(s.address),
        }
        for s in sites
    ]
    rooms_rows = [
        {
            "id": r.id,
            "site_id": r.site_id,
            "code": r.code,
            "description": _sanitize_freetext(r.description),
        }
        for r in rooms
    ]
    switches_rows = [
        {
            "id": s.id,
            # Free-text-ish fields set by the operator (or a CSV import) —
            # sanitised for the same prompt-injection reason as the
            # dedicated description/notes fields below.
            "name": _sanitize_freetext(s.name),
            "vendor": _sanitize_freetext(s.vendor),
            "model": _sanitize_freetext(s.model),
            "room_id": s.room_id,
            # Derived for convenience; not a column on switches.
            "site_id": room_to_site.get(s.room_id) if s.room_id else None,
            "port_count": s.port_count,
            "description": _sanitize_freetext(s.description),
        }
        for s in switches
    ]
    ports_rows = [
        {
            "id": p.id,
            "switch_id": p.switch_id,
            "number": p.number,
            "label": _sanitize_freetext(p.label),
            "mode": p.mode.value if p.mode else None,
            "native_vlan_id": p.native_vlan_id,
            "admin_status": p.admin_status.value if p.admin_status else None,
            "connected_device_id": p.connected_device_id,
            "connected_device_name": (
                _sanitize_freetext(devices_by_id[p.connected_device_id].name)
                if p.connected_device_id in devices_by_id
                else None
            ),
            # Notes can hold operator hints like "uplink to SW-CORE-01" —
            # the single most-useful free-text field for linking.
            "notes": _sanitize_freetext(p.notes),
        }
        for p in ports
    ]
    vlans_rows = [
        {"id": v.id, "vlan_id": v.vlan_id, "name": _sanitize_freetext(v.name)}
        for v in vlans
    ]
    subnets_rows = [
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
    ]
    existing_links_rows = [
        {"port_a_id": link.port_a_id, "port_b_id": link.port_b_id}
        for link in links
    ]

    # Cap each entity list independently and collect a human-readable note
    # for every type that got truncated — surfaced on the snapshot so the
    # LLM (and anyone debugging a weird answer) knows the data was partial.
    truncation_notes: list[str] = []
    capped: dict[str, list[dict[str, Any]]] = {}
    for label, rows in (
        ("sites", sites_rows),
        ("rooms", rooms_rows),
        ("switches", switches_rows),
        ("ports", ports_rows),
        ("vlans", vlans_rows),
        ("subnets", subnets_rows),
        ("existing_links", existing_links_rows),
    ):
        capped_rows, note = _cap_entities(label, rows)
        capped[label] = capped_rows
        if note:
            truncation_notes.append(note)

    return {
        "sites": capped["sites"],
        "rooms": capped["rooms"],
        "switches": capped["switches"],
        "ports": capped["ports"],
        "vlans": capped["vlans"],
        "subnets": capped["subnets"],
        "existing_links": capped["existing_links"],
        # Empty when nothing was truncated. Explicit rather than omitted so
        # callers (and the LLM's system prompt) can rely on the key always
        # being present.
        "truncation_notes": truncation_notes,
    }
