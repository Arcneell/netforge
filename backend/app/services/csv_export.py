"""CSV export — streams one row per entity instance, with FKs denormalized.

The output format matches `csv_import.py` so a round-trip
`export → edit in Excel → re-import` works.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from collections.abc import AsyncIterator
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.core import Room, Site
from app.models.device import Device
from app.models.ip import Ip
from app.models.link import Link
from app.models.port import Port, PortVlan
from app.models.subnet import Subnet
from app.models.switch import Switch
from app.models.user import AuditLog, User
from app.models.vlan import Vlan

ENTITIES = (
    "sites",
    "rooms",
    "vlans",
    "subnets",
    "ips",
    "devices",
    "switches",
    "ports",
    "links",
)


def _line(writer: csv.writer, buffer: io.StringIO, cells: list[str]) -> str:
    """Write one CSV line, return what was just written and clear the buffer."""
    writer.writerow(cells)
    out = buffer.getvalue()
    buffer.seek(0)
    buffer.truncate()
    return out


def _str_or_empty(value: object) -> str:
    return "" if value is None else str(value)


def _bool_or_empty(value: object) -> str:
    if value is None:
        return ""
    return "true" if value else "false"


async def stream_export(db: AsyncSession, entity: str) -> AsyncIterator[str]:
    """Yield the export as CSV chunks. First chunk includes the BOM so
    Excel auto-detects UTF-8."""
    if entity not in ENTITIES:
        raise ValueError(f"Unknown entity: {entity!r}")

    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL)

    if entity == "sites":
        yield "﻿" + _line(writer, buf, ["code", "name", "address"])
        rows = (await db.execute(select(Site).order_by(Site.code))).scalars().all()
        for s in rows:
            yield _line(writer, buf, [s.code, s.name, _str_or_empty(s.address)])

    elif entity == "rooms":
        yield "﻿" + _line(writer, buf, ["site_code", "code", "description"])
        q = (
            select(Room, Site.code)
            .join(Site, Room.site_id == Site.id)
            .order_by(Site.code, Room.code)
        )
        for room, site_code in (await db.execute(q)).all():
            yield _line(
                writer,
                buf,
                [site_code, room.code, _str_or_empty(room.description)],
            )

    elif entity == "vlans":
        yield "﻿" + _line(writer, buf, ["vlan_id", "name", "description", "color"])
        rows = (await db.execute(select(Vlan).order_by(Vlan.vlan_id))).scalars().all()
        for v in rows:
            yield _line(
                writer,
                buf,
                [
                    str(v.vlan_id),
                    v.name,
                    _str_or_empty(v.description),
                    _str_or_empty(v.color),
                ],
            )

    elif entity == "subnets":
        yield "﻿" + _line(
            writer,
            buf,
            [
                "cidr", "gateway", "vlan_id", "site_code", "description",
                "dhcp_enabled", "dhcp_range_start", "dhcp_range_end",
            ],
        )
        q = (
            select(Subnet, Site.code, Vlan.vlan_id)
            .join(Site, Subnet.site_id == Site.id)
            .outerjoin(Vlan, Subnet.vlan_id == Vlan.id)
            .order_by(Subnet.cidr)
        )
        for subnet, site_code, vlan_public_id in (await db.execute(q)).all():
            yield _line(
                writer,
                buf,
                [
                    str(subnet.cidr),
                    _str_or_empty(subnet.gateway),
                    _str_or_empty(vlan_public_id),
                    site_code,
                    _str_or_empty(subnet.description),
                    _bool_or_empty(subnet.dhcp_enabled),
                    _str_or_empty(subnet.dhcp_range_start),
                    _str_or_empty(subnet.dhcp_range_end),
                ],
            )

    elif entity == "ips":
        yield "﻿" + _line(
            writer,
            buf,
            ["address", "status", "hostname", "mac", "device_name", "description"],
        )
        q = (
            select(Ip, Device.name)
            .outerjoin(Device, Ip.device_id == Device.id)
            .order_by(Ip.address)
        )
        for ip, device_name in (await db.execute(q)).all():
            yield _line(
                writer,
                buf,
                [
                    str(ip.address),
                    ip.status.value if hasattr(ip.status, "value") else str(ip.status),
                    _str_or_empty(ip.hostname),
                    _str_or_empty(ip.mac),
                    _str_or_empty(device_name),
                    _str_or_empty(ip.description),
                ],
            )

    elif entity == "devices":
        yield "﻿" + _line(
            writer,
            buf,
            ["name", "type", "vendor", "model", "serial", "site_code", "room_code", "description"],
        )
        q = (
            select(Device, Site.code.label("site_code"), Room.code.label("room_code"))
            .outerjoin(Room, Device.room_id == Room.id)
            .outerjoin(Site, Room.site_id == Site.id)
            .order_by(Device.name)
        )
        for device, site_code, room_code in (await db.execute(q)).all():
            yield _line(
                writer,
                buf,
                [
                    device.name,
                    device.type.value if hasattr(device.type, "value") else str(device.type),
                    _str_or_empty(device.vendor),
                    _str_or_empty(device.model),
                    _str_or_empty(device.serial),
                    _str_or_empty(site_code),
                    _str_or_empty(room_code),
                    _str_or_empty(device.description),
                ],
            )

    elif entity == "switches":
        yield "﻿" + _line(
            writer,
            buf,
            [
                "name", "vendor", "model", "serial", "management_ip",
                "site_code", "room_code", "rack_position", "port_count",
                "firmware_version",
            ],
        )
        q = (
            select(Switch, Site.code.label("site_code"), Room.code.label("room_code"))
            .outerjoin(Room, Switch.room_id == Room.id)
            .outerjoin(Site, Room.site_id == Site.id)
            .order_by(Switch.name)
        )
        for sw, site_code, room_code in (await db.execute(q)).all():
            yield _line(
                writer,
                buf,
                [
                    sw.name,
                    _str_or_empty(sw.vendor),
                    _str_or_empty(sw.model),
                    _str_or_empty(sw.serial),
                    _str_or_empty(sw.management_ip),
                    _str_or_empty(site_code),
                    _str_or_empty(room_code),
                    _str_or_empty(sw.rack_position),
                    str(sw.port_count),
                    _str_or_empty(sw.firmware_version),
                ],
            )

    elif entity == "ports":
        yield "﻿" + _line(
            writer,
            buf,
            [
                "switch_name", "number", "label", "mode", "native_vlan",
                "trunk_vlans", "admin_status", "device_name", "connected_ip",
                "notes",
            ],
        )
        q = (
            select(Port, Switch.name)
            .join(Switch, Port.switch_id == Switch.id)
            .options(
                selectinload(Port.tagged_vlans).selectinload(PortVlan.vlan),
                selectinload(Port.native_vlan),
                selectinload(Port.connected_device),
                selectinload(Port.connected_ip),
            )
            .order_by(Switch.name, Port.number)
        )
        for port, switch_name in (await db.execute(q)).all():
            tagged = ",".join(
                str(pv.vlan.vlan_id)
                for pv in port.tagged_vlans
                if pv.vlan is not None
            )
            yield _line(
                writer,
                buf,
                [
                    switch_name,
                    str(port.number),
                    _str_or_empty(port.label),
                    port.mode.value if hasattr(port.mode, "value") else str(port.mode),
                    _str_or_empty(
                        port.native_vlan.vlan_id if port.native_vlan else None
                    ),
                    tagged,
                    port.admin_status.value if hasattr(port.admin_status, "value") else str(port.admin_status),
                    _str_or_empty(
                        port.connected_device.name if port.connected_device else None
                    ),
                    _str_or_empty(
                        port.connected_ip.address if port.connected_ip else None
                    ),
                    _str_or_empty(port.notes),
                ],
            )

    elif entity == "links":
        yield "﻿" + _line(
            writer,
            buf,
            ["switch_a", "port_a", "switch_b", "port_b", "link_type", "speed_mbps", "description"],
        )
        Port_a = Port.__table__.alias("port_a")
        Port_b = Port.__table__.alias("port_b")
        Switch_a = Switch.__table__.alias("switch_a")
        Switch_b = Switch.__table__.alias("switch_b")
        q = (
            select(
                Link,
                Switch_a.c.name.label("switch_a_name"),
                Port_a.c.number.label("port_a_num"),
                Switch_b.c.name.label("switch_b_name"),
                Port_b.c.number.label("port_b_num"),
            )
            .join(Port_a, Link.port_a_id == Port_a.c.id)
            .join(Switch_a, Port_a.c.switch_id == Switch_a.c.id)
            .join(Port_b, Link.port_b_id == Port_b.c.id)
            .join(Switch_b, Port_b.c.switch_id == Switch_b.c.id)
            .order_by(Link.id)
        )
        for link, sa, pa, sb, pb in (await db.execute(q)).all():
            yield _line(
                writer,
                buf,
                [
                    sa,
                    str(pa),
                    sb,
                    str(pb),
                    link.link_type.value if hasattr(link.link_type, "value") else str(link.link_type),
                    _str_or_empty(link.speed_mbps),
                    _str_or_empty(link.description),
                ],
            )


async def stream_audit_export(
    db: AsyncSession,
    *,
    entity: str | None = None,
    entity_id: int | None = None,
    user_id: int | None = None,
    from_: datetime | None = None,
    to: datetime | None = None,
) -> AsyncIterator[str]:
    """Stream the audit log as CSV, applying the same filters as `GET /api/audit`.

    Joining `users` keeps the export self-contained — admins want to know who
    did something without having to cross-reference user ids by hand. The
    `changes` dict is serialised as compact JSON in one column; trying to flatten
    it into named columns would explode the header for what's already a debug
    field.
    """
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL)

    yield "﻿" + _line(
        writer,
        buf,
        [
            "id",
            "created_at",
            "user_id",
            "user_email",
            "action",
            "entity",
            "entity_id",
            "ip_address",
            "user_agent",
            "changes",
        ],
    )

    q = (
        select(AuditLog, User.email)
        .outerjoin(User, AuditLog.user_id == User.id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    )
    if entity is not None:
        q = q.where(AuditLog.entity == entity)
    if entity_id is not None:
        q = q.where(AuditLog.entity_id == entity_id)
    if user_id is not None:
        q = q.where(AuditLog.user_id == user_id)
    if from_ is not None:
        q = q.where(AuditLog.created_at >= from_)
    if to is not None:
        q = q.where(AuditLog.created_at <= to)

    for entry, user_email in (await db.execute(q)).all():
        yield _line(
            writer,
            buf,
            [
                str(entry.id),
                entry.created_at.isoformat(),
                _str_or_empty(entry.user_id),
                _str_or_empty(user_email),
                entry.action.value if hasattr(entry.action, "value") else str(entry.action),
                entry.entity,
                _str_or_empty(entry.entity_id),
                _str_or_empty(entry.ip_address),
                _str_or_empty(entry.user_agent),
                # Compact JSON keeps newlines/commas out of the cell — Excel
                # then opens this column cleanly with `;` as the separator.
                "" if entry.changes is None else json.dumps(entry.changes, ensure_ascii=False),
            ],
        )


async def build_zip(db: AsyncSession) -> bytes:
    """Bundle every entity's CSV export into a single ZIP archive.

    The archive structure mirrors what the bulk importer expects: one
    `<entity>.csv` per entity, named exactly the way the auto-detect endpoint
    finds them. Drop the ZIP back into the import view and it round-trips —
    that's the whole point of this endpoint as a backup / migration tool.

    We assemble in memory rather than streaming the ZIP because:
      - the realistic v1 dataset (< 200 switches, a few thousand IPs) is well
        under a few MB uncompressed, so RAM cost is negligible;
      - streaming a ZIP needs each member's CRC32 + size up front (or the
        slow "data descriptor" extension), which would mean either two
        passes over each entity or shelling out to a streaming-zip lib.
        Not worth the complexity for v1.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(
        buf, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as zf:
        for entity in ENTITIES:
            chunks: list[str] = []
            async for chunk in stream_export(db, entity):
                chunks.append(chunk)
            zf.writestr(f"{entity}.csv", "".join(chunks).encode("utf-8"))
    return buf.getvalue()
