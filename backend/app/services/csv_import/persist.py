"""Persist functions — one per entity.

They upsert by the natural key and DO NOT commit. The driver commits (or rolls
back) once for the whole batch.

Each one also feeds the reference cache (`remember_*` / `invalidate_*`) with
whatever it creates, so a later row — or a later file in the same bulk import
— resolves against entities this very transaction inserted.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import Room, Site
from app.models.device import Device
from app.models.ip import Ip
from app.models.link import Link
from app.models.port import Port, PortAdminStatus, PortMode, PortVlan
from app.models.subnet import Subnet
from app.models.switch import Switch
from app.models.vlan import Vlan
from app.services.csv_import.errors import _RefError
from app.services.csv_import.refs import (
    _device_by_name,
    _find_subnet_for,
    _port_on_switch,
    _refs,
    _room_by_codes,
    _site_by_code,
    _switch_by_name,
    _vlan_by_id,
)
from app.services.csv_import.rows import (
    _DeviceRow,
    _IpRow,
    _LinkRow,
    _PortRow,
    _RoomRow,
    _SiteRow,
    _SubnetRow,
    _SwitchRow,
    _VlanRow,
)


async def _persist_site(db: AsyncSession, row: _SiteRow) -> None:
    refs = _refs(db)
    existing = await refs.site_by_code(row.code)
    if existing is None:
        site = Site(code=row.code, name=row.name, address=row.address)
        db.add(site)
        refs.remember_site(site)
    else:
        existing.name = row.name
        if row.address is not None:
            existing.address = row.address


async def _persist_room(db: AsyncSession, row: _RoomRow) -> None:
    site = await _site_by_code(db, row.site_code)
    assert site is not None  # `site_code` is required on the row model
    refs = _refs(db)
    existing = await refs.room_by_code(site.id, row.code)
    if existing is None:
        room = Room(site_id=site.id, code=row.code, description=row.description)
        db.add(room)
        refs.remember_room(site.id, row.code, room)
    elif row.description is not None:
        existing.description = row.description


async def _persist_vlan(db: AsyncSession, row: _VlanRow) -> None:
    refs = _refs(db)
    existing = await refs.vlan_by_public_id(row.vlan_id)
    if existing is None:
        vlan = Vlan(**row.model_dump())
        db.add(vlan)
        refs.remember_vlan(vlan)
    else:
        existing.name = row.name
        if row.description is not None:
            existing.description = row.description
        if row.color is not None:
            existing.color = row.color


async def _persist_subnet(db: AsyncSession, row: _SubnetRow) -> None:
    site = await _site_by_code(db, row.site_code)
    assert site is not None  # `site_code` is required on the row model
    vlan = await _vlan_by_id(db, row.vlan_id)

    # Keep dhcp_enabled tri-state on the upsert path (True / False / None)
    # so a blank cell leaves the existing value untouched. The previous
    # `... if not None else False` collapsed blank → False, then the loop
    # below (`if v is not None …`) ran setattr unconditionally — silently
    # disabling DHCP on every subnet when an operator re-imported a CSV
    # that didn't carry the column. The new-row branch still defaults to
    # False (matches the column server-side default + NOT NULL constraint).
    data: dict[str, Any] = {
        "cidr": row.cidr,
        "gateway": row.gateway,
        "vlan_id": vlan.id if vlan else None,
        "site_id": site.id,
        "description": row.description,
        "dhcp_enabled": row.dhcp_enabled,
        "dhcp_range_start": row.dhcp_range_start,
        "dhcp_range_end": row.dhcp_range_end,
    }

    refs = _refs(db)
    existing = await refs.subnet_by_cidr(row.cidr)
    if existing is None:
        create_data = {**data, "dhcp_enabled": bool(data["dhcp_enabled"])}
        subnet = Subnet(**create_data)
        db.add(subnet)
        refs.remember_subnet(subnet)
    else:
        # Fields where blank CSV cells are an explicit "clear this value"
        # signal — anything outside this set treats None as "leave alone".
        clearable = ("vlan_id", "gateway", "dhcp_range_start", "dhcp_range_end")
        for k, v in data.items():
            if v is None and k not in clearable:
                continue
            setattr(existing, k, v)
    # The containment index built for `ips` rows must see this write; drop it
    # so the next lookup re-snapshots the table (see `invalidate_subnet_index`).
    refs.invalidate_subnet_index()


async def _persist_ip(db: AsyncSession, row: _IpRow) -> None:
    subnet = await _find_subnet_for(db, row.address)
    device = await _device_by_name(db, row.device_name)

    refs = _refs(db)
    existing = await refs.ip_by_address(row.address)
    data = {
        "subnet_id": subnet.id,
        "address": row.address,
        "status": row.status,
        "hostname": row.hostname,
        "mac": row.mac,
        "device_id": device.id if device else None,
        "description": row.description,
    }
    if existing is None:
        ip = Ip(**data)
        db.add(ip)
        refs.remember_ip(ip)
    else:
        # Upsert: replace every column. Empty CSV cells keep the existing
        # value untouched ONLY for fields documented as such; here we treat
        # status + subnet_id as authoritative since they are mandatory.
        existing.subnet_id = subnet.id
        existing.status = row.status
        if row.hostname is not None:
            existing.hostname = row.hostname
        if row.mac is not None:
            existing.mac = row.mac
        if device is not None:
            existing.device_id = device.id
        if row.description is not None:
            existing.description = row.description


async def _persist_device(db: AsyncSession, row: _DeviceRow) -> None:
    room = await _room_by_codes(db, row.site_code, row.room_code)
    refs = _refs(db)
    existing = await refs.device_by_name(row.name)
    data = {
        "name": row.name,
        "type": row.type,
        "vendor": row.vendor,
        "model": row.model,
        "serial": row.serial,
        "room_id": room.id if room else None,
        "description": row.description,
    }
    if existing is None:
        device = Device(**data)
        db.add(device)
        refs.remember_device(device)
    else:
        existing.type = row.type
        for k in ("vendor", "model", "serial", "description"):
            v = getattr(row, k)
            if v is not None:
                setattr(existing, k, v)
        if room is not None:
            existing.room_id = room.id


async def _persist_switch(db: AsyncSession, row: _SwitchRow) -> None:
    room = await _room_by_codes(db, row.site_code, row.room_code)
    refs = _refs(db)
    existing = await refs.switch_by_name(row.name)
    if existing is None:
        switch = Switch(
            name=row.name,
            vendor=row.vendor,
            model=row.model,
            serial=row.serial,
            management_ip=row.management_ip,
            room_id=room.id if room else None,
            rack_position=row.rack_position,
            port_count=row.port_count,
            firmware_version=row.firmware_version,
        )
        for n in range(1, row.port_count + 1):
            switch.ports.append(
                Port(number=n, mode=PortMode.access, admin_status=PortAdminStatus.up)
            )
        db.add(switch)
        refs.remember_switch(switch)
    else:
        if row.port_count < existing.port_count:
            raise _RefError(
                "port_count",
                row.port_count,
                f"Switch {row.name!r} already has {existing.port_count} ports; "
                "shrinking port_count via CSV import is refused.",
            )
        if row.port_count > existing.port_count:
            # Don't touch `existing.ports` — that would lazy-load the whole
            # relationship inside the async session and trip MissingGreenlet.
            # Insert by FK instead; cascades + uniqueness are guarded at the
            # DB level so this is equivalent.
            for n in range(existing.port_count + 1, row.port_count + 1):
                db.add(
                    Port(
                        switch_id=existing.id,
                        number=n,
                        mode=PortMode.access,
                        admin_status=PortAdminStatus.up,
                    )
                )
            existing.port_count = row.port_count
            # Port numbers that legitimately missed a moment ago now exist.
            refs.forget_ports_of_switch(existing.id)
        for k in (
            "vendor",
            "model",
            "serial",
            "management_ip",
            "rack_position",
            "firmware_version",
        ):
            v = getattr(row, k)
            if v is not None:
                setattr(existing, k, v)
        if room is not None:
            existing.room_id = room.id


async def _persist_port(db: AsyncSession, row: _PortRow) -> None:
    switch = await _switch_by_name(db, row.switch_name, column="switch_name")
    port = await _port_on_switch(db, switch, row.number, column="number")

    native_vlan = await _vlan_by_id(db, row.native_vlan, column="native_vlan")
    device = await _device_by_name(db, row.device_name)

    port.label = row.label if row.label is not None else port.label
    port.mode = row.mode
    port.native_vlan_id = native_vlan.id if native_vlan else None
    port.admin_status = row.admin_status
    if device is not None:
        port.connected_device_id = device.id
    if row.notes is not None:
        port.notes = row.notes
    if row.connected_ip is not None:
        ip_row = await _refs(db).ip_by_address(row.connected_ip)
        if ip_row is None:
            raise _RefError(
                "connected_ip", row.connected_ip, f"IP {row.connected_ip} not found"
            )
        port.connected_ip_id = ip_row.id

    # Trunk VLANs: full replacement of the tagged set.
    if row.trunk_vlans is not None:
        # Resolve VLAN public ids → DB ids.
        wanted_ids: list[int] = []
        for vid in row.trunk_vlans:
            vlan = await _vlan_by_id(db, vid, column="trunk_vlans")
            if vlan is None:
                # Only reachable if `vid` were None — the helper raises
                # _RefError for an unknown id. Kept so the checker can narrow.
                raise _RefError("trunk_vlans", vid, f"VLAN {vid} not found")
            if vlan.id == port.native_vlan_id:
                raise _RefError(
                    "trunk_vlans",
                    vid,
                    f"VLAN {vid} is the native VLAN of this port — cannot also tag it.",
                )
            wanted_ids.append(vlan.id)
        wanted_set: set[int] = set(wanted_ids)
        existing_pv = (
            (await db.execute(select(PortVlan).where(PortVlan.port_id == port.id)))
            .scalars()
            .all()
        )
        existing_ids = {pv.vlan_id for pv in existing_pv}
        # Symmetric diff: only delete rows that are leaving the set, only
        # insert rows that are joining it. Avoids the case where a naive
        # "delete all + insert all" queues both operations in the same
        # flush and Postgres trips port_vlan_pk because the INSERT for an
        # unchanged (port_id, vlan_id) pair fires before the matching
        # DELETE materialises — perfectly valid CSV input would roll back
        # the whole import with a confusing INTEGRITY_VIOLATION.
        for pv in existing_pv:
            if pv.vlan_id not in wanted_set:
                await db.delete(pv)
        for vid in wanted_ids:
            if vid not in existing_ids:
                db.add(PortVlan(port_id=port.id, vlan_id=vid))


async def _persist_link(db: AsyncSession, row: _LinkRow) -> None:
    sa = await _switch_by_name(db, row.switch_a, column="switch_a")
    sb = await _switch_by_name(db, row.switch_b, column="switch_b")
    pa = await _port_on_switch(db, sa, row.port_a, column="port_a")
    pb = await _port_on_switch(db, sb, row.port_b, column="port_b")

    if pa.id == pb.id:
        raise _RefError("port_a", row.port_a, "Cannot link a port to itself")

    a_id, b_id = (pa.id, pb.id) if pa.id < pb.id else (pb.id, pa.id)

    refs = _refs(db)
    existing = await refs.link_by_ports(a_id, b_id)

    data = {
        "link_type": row.link_type,
        "speed_mbps": row.speed_mbps,
        "description": row.description,
    }
    if existing is None:
        link = Link(port_a_id=a_id, port_b_id=b_id, **data)
        db.add(link)
        refs.remember_link(a_id, b_id, link)
    else:
        existing.link_type = row.link_type
        if row.speed_mbps is not None:
            existing.speed_mbps = row.speed_mbps
        if row.description is not None:
            existing.description = row.description


# --------------------------------------------------------------------------- #
# Registry — wires each entity name to its row schema + persist callable.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _ImportSpec:
    row_model: type[BaseModel]
    persist: Callable[[AsyncSession, Any], Awaitable[None]]


SPECS: dict[str, _ImportSpec] = {
    "sites": _ImportSpec(_SiteRow, _persist_site),
    "rooms": _ImportSpec(_RoomRow, _persist_room),
    "vlans": _ImportSpec(_VlanRow, _persist_vlan),
    "subnets": _ImportSpec(_SubnetRow, _persist_subnet),
    "ips": _ImportSpec(_IpRow, _persist_ip),
    "devices": _ImportSpec(_DeviceRow, _persist_device),
    "switches": _ImportSpec(_SwitchRow, _persist_switch),
    "ports": _ImportSpec(_PortRow, _persist_port),
    "links": _ImportSpec(_LinkRow, _persist_link),
}

# Dependency order — used when multiple CSVs are imported in one shot. Mirrors
# the recommended sequence in docs/08-import-csv.md: parents before children,
# `ports` after `ips` so port → ip refs resolve, `links` last because it
# resolves ports.
IMPORT_ORDER: tuple[str, ...] = (
    "sites",
    "rooms",
    "vlans",
    "subnets",
    "devices",
    "switches",
    "ips",
    "ports",
    "links",
)
