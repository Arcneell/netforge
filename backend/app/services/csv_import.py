"""CSV import — parsing, validation, per-entity upsert.

Conventions (see docs/08-import-csv.md):
  - Delimiter `;`, encoding `utf-8-sig` (Excel FR-compatible).
  - First line = headers (case-sensitive).
  - Reference columns (`site_code`, `vlan_id`, ...) are resolved against the
    current DB content; a missing reference produces a row-level error.
  - Upsert by the natural key called out in each `_Row` model docstring.
  - The whole import runs in a single transaction. On any error the
    transaction rolls back and the report lists everything we know.
  - `dry_run=True` always rolls back even on success.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import Room, Site
from app.models.device import Device, DeviceType
from app.models.ip import Ip, IpStatus
from app.models.link import Link, LinkType
from app.models.port import Port, PortAdminStatus, PortMode, PortVlan
from app.models.subnet import Subnet
from app.models.switch import Switch
from app.models.vlan import Vlan
from app.schemas.imports import (
    BulkImportFileReport,
    BulkImportReport,
    DetectReport,
    ImportErrorRow,
    ImportReport,
)

# --------------------------------------------------------------------------- #
# Row models — one Pydantic class per entity, mapping the CSV column names.
# --------------------------------------------------------------------------- #


def _coerce_bool(v: Any) -> bool | None:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "y", "vrai", "oui"):
        return True
    if s in ("0", "false", "no", "n", "faux", "non"):
        return False
    raise ValueError(f"invalid boolean: {v!r}")


def _empty_to_none(v: Any) -> Any:
    return None if (v is None or v == "") else v


class _SiteRow(BaseModel):
    """Upsert by `code`."""

    code: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=200)
    address: str | None = None


class _RoomRow(BaseModel):
    """Upsert by (site_code, code)."""

    site_code: str = Field(min_length=1, max_length=20)
    code: str = Field(min_length=1, max_length=50)
    description: str | None = None


class _VlanRow(BaseModel):
    """Upsert by `vlan_id`."""

    vlan_id: int = Field(ge=1, le=4094)
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")

    @field_validator("color", mode="before")
    @classmethod
    def _empty_color_to_none(cls, v: Any) -> Any:
        # Blank cells exported by the CSV writer must round-trip — otherwise
        # re-importing any export with VLANs missing a color fails the pattern.
        return _empty_to_none(v)


class _SubnetRow(BaseModel):
    """Upsert by `cidr`."""

    cidr: str
    gateway: str | None = None
    vlan_id: int | None = Field(default=None, ge=1, le=4094)
    site_code: str = Field(min_length=1, max_length=20)
    description: str | None = None
    dhcp_enabled: bool | None = None
    dhcp_range_start: str | None = None
    dhcp_range_end: str | None = None

    @field_validator("cidr", mode="before")
    @classmethod
    def _validate_cidr(cls, v: Any) -> str:
        return str(IPv4Network(v, strict=False))

    @field_validator("gateway", "dhcp_range_start", "dhcp_range_end", mode="before")
    @classmethod
    def _validate_address(cls, v: Any) -> str | None:
        v = _empty_to_none(v)
        return None if v is None else str(IPv4Address(v))

    @field_validator("vlan_id", mode="before")
    @classmethod
    def _empty_vlan_to_none(cls, v: Any) -> Any:
        # Without this, a blank vlan_id cell (subnet without an assigned VLAN
        # — perfectly valid since the field is Optional) would fail Pydantic's
        # int parsing. Mirrors the same coercion applied to every other
        # nullable cell in this model.
        return _empty_to_none(v)

    @field_validator("dhcp_enabled", mode="before")
    @classmethod
    def _coerce_bool(cls, v: Any) -> bool | None:
        return _coerce_bool(v)


# Three MAC presentations Cisco / HP / Aruba all happen to emit.
_MAC_PATTERNS = (
    re.compile(r"^[0-9a-fA-F]{2}([:-][0-9a-fA-F]{2}){5}$"),
    re.compile(r"^[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}$"),
)


def _normalize_mac(v: Any) -> str | None:
    v = _empty_to_none(v)
    if v is None:
        return None
    s = str(v).lower().strip()
    for pat in _MAC_PATTERNS:
        if pat.match(s):
            digits = re.sub(r"[^0-9a-f]", "", s)
            return ":".join(digits[i : i + 2] for i in range(0, 12, 2))
    raise ValueError(f"invalid MAC address: {v!r}")


class _IpRow(BaseModel):
    """Upsert by `address`. `subnet_id` is derived from the CIDR that contains
    the address — no need to specify it. `device_name` is optional; if given
    it must reference an existing device."""

    address: str
    status: IpStatus
    hostname: str | None = Field(default=None, max_length=255)
    mac: str | None = None
    device_name: str | None = None
    description: str | None = None

    @field_validator("address", mode="before")
    @classmethod
    def _validate_address(cls, v: Any) -> str:
        return str(IPv4Address(v))

    @field_validator("mac", mode="before")
    @classmethod
    def _validate_mac(cls, v: Any) -> str | None:
        return _normalize_mac(v)


class _DeviceRow(BaseModel):
    """Upsert by `name`."""

    name: str = Field(min_length=1, max_length=255)
    type: DeviceType
    vendor: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    serial: str | None = Field(default=None, max_length=100)
    site_code: str | None = None
    room_code: str | None = None
    description: str | None = None


class _SwitchRow(BaseModel):
    """Upsert by `name`. On create, generates `port_count` ports."""

    name: str = Field(min_length=1, max_length=100)
    vendor: str | None = Field(default=None, max_length=50)
    model: str | None = Field(default=None, max_length=100)
    serial: str | None = Field(default=None, max_length=100)
    management_ip: str | None = None
    # `room_id` is nullable on Switch — let blank cells round-trip on export.
    # Either both site/room codes are set (switch is in a room) or neither.
    site_code: str | None = Field(default=None, max_length=20)
    room_code: str | None = Field(default=None, max_length=50)
    rack_position: str | None = Field(default=None, max_length=20)
    port_count: int = Field(gt=0, le=1024)
    firmware_version: str | None = Field(default=None, max_length=50)

    @field_validator("site_code", "room_code", mode="before")
    @classmethod
    def _blank_code_to_none(cls, v: Any) -> Any:
        return _empty_to_none(v)

    @field_validator("management_ip", mode="before")
    @classmethod
    def _validate_ip(cls, v: Any) -> str | None:
        v = _empty_to_none(v)
        return None if v is None else str(IPv4Address(v))

    @model_validator(mode="after")
    def _both_or_neither_location(self) -> _SwitchRow:
        # Without this, a row like `site_code=PAR;room_code=` would silently
        # land in the DB as roomless — and the supplied site code would never
        # be validated against the sites table. Force the user to either fill
        # both cells (switch lives in a room) or leave both blank (roomless).
        if (self.site_code is None) != (self.room_code is None):
            raise ValueError(
                "site_code and room_code must both be set or both be blank"
            )
        return self


def _parse_csv_list(v: Any) -> list[int] | None:
    v = _empty_to_none(v)
    if v is None:
        return None
    return [int(x.strip()) for x in str(v).split(",") if x.strip()]


class _PortRow(BaseModel):
    """Update-only — ports are created automatically with their switch.
    Upsert by (switch_name, number)."""

    switch_name: str = Field(min_length=1, max_length=100)
    number: int = Field(gt=0)
    label: str | None = Field(default=None, max_length=100)
    mode: PortMode = PortMode.access
    native_vlan: int | None = Field(default=None, ge=1, le=4094)
    trunk_vlans: list[int] | None = None
    admin_status: PortAdminStatus = PortAdminStatus.up
    device_name: str | None = None
    connected_ip: str | None = None
    notes: str | None = None

    @field_validator("trunk_vlans", mode="before")
    @classmethod
    def _split(cls, v: Any) -> list[int] | None:
        return _parse_csv_list(v)

    @field_validator("native_vlan", mode="before")
    @classmethod
    def _empty_vlan_to_none(cls, v: Any) -> Any:
        # Same fix as _SubnetRow.vlan_id — blank cells are valid (access port
        # with no native VLAN set yet) and must coerce to None before Pydantic
        # tries to parse them as int.
        return _empty_to_none(v)

    @field_validator("connected_ip", mode="before")
    @classmethod
    def _validate_ip(cls, v: Any) -> str | None:
        v = _empty_to_none(v)
        return None if v is None else str(IPv4Address(v))


class _LinkRow(BaseModel):
    """Upsert by the (canonical) tuple of the two endpoints."""

    switch_a: str = Field(min_length=1, max_length=100)
    port_a: int = Field(gt=0)
    switch_b: str = Field(min_length=1, max_length=100)
    port_b: int = Field(gt=0)
    link_type: LinkType = LinkType.copper
    speed_mbps: int | None = Field(default=None, gt=0)
    description: str | None = None

    @field_validator("speed_mbps", mode="before")
    @classmethod
    def _empty_speed_to_none(cls, v: Any) -> Any:
        # Same fix again — speed_mbps is optional and a blank cell must
        # become None, not trigger an int-parse error.
        return _empty_to_none(v)


# --------------------------------------------------------------------------- #
# Reference resolvers — small async helpers used by persist().
# --------------------------------------------------------------------------- #


class _RefError(Exception):
    """Raised when a CSV row points at an entity that does not exist."""

    def __init__(self, column: str, value: Any, message: str) -> None:
        self.column = column
        self.value = "" if value is None else str(value)
        self.message = message
        super().__init__(message)


async def _site_by_code(db: AsyncSession, code: str | None, column: str = "site_code") -> Site | None:
    if not code:
        return None
    result = await db.execute(select(Site).where(Site.code == code))
    site = result.scalar_one_or_none()
    if site is None:
        raise _RefError(column, code, f"Site code {code!r} not found")
    return site


async def _room_by_codes(
    db: AsyncSession, site_code: str | None, room_code: str | None
) -> Room | None:
    if not site_code or not room_code:
        return None
    site = await _site_by_code(db, site_code, column="site_code")
    result = await db.execute(
        select(Room).where(Room.site_id == site.id, Room.code == room_code)
    )
    room = result.scalar_one_or_none()
    if room is None:
        raise _RefError("room_code", room_code, f"Room code {room_code!r} not found in site {site_code!r}")
    return room


async def _vlan_by_id(db: AsyncSession, vlan_id: int | None, column: str = "vlan_id") -> Vlan | None:
    if vlan_id is None:
        return None
    result = await db.execute(select(Vlan).where(Vlan.vlan_id == vlan_id))
    vlan = result.scalar_one_or_none()
    if vlan is None:
        raise _RefError(column, vlan_id, f"VLAN {vlan_id} not found")
    return vlan


async def _device_by_name(
    db: AsyncSession, name: str | None, column: str = "device_name"
) -> Device | None:
    if not name:
        return None
    result = await db.execute(select(Device).where(Device.name == name))
    device = result.scalar_one_or_none()
    if device is None:
        raise _RefError(column, name, f"Device {name!r} not found")
    return device


async def _switch_by_name(db: AsyncSession, name: str, column: str) -> Switch:
    result = await db.execute(select(Switch).where(Switch.name == name))
    switch = result.scalar_one_or_none()
    if switch is None:
        raise _RefError(column, name, f"Switch {name!r} not found")
    return switch


async def _port_on_switch(
    db: AsyncSession, switch: Switch, number: int, column: str
) -> Port:
    result = await db.execute(
        select(Port).where(Port.switch_id == switch.id, Port.number == number)
    )
    port = result.scalar_one_or_none()
    if port is None:
        raise _RefError(column, number, f"Port {number} not found on switch {switch.name!r}")
    return port


# --------------------------------------------------------------------------- #
# Persist functions — one per entity. They upsert by the natural key and
# DO NOT commit. The driver commits (or rolls back) once for the whole batch.
# --------------------------------------------------------------------------- #


async def _persist_site(db: AsyncSession, row: _SiteRow) -> None:
    existing = (
        await db.execute(select(Site).where(Site.code == row.code))
    ).scalar_one_or_none()
    if existing is None:
        db.add(Site(code=row.code, name=row.name, address=row.address))
    else:
        existing.name = row.name
        if row.address is not None:
            existing.address = row.address


async def _persist_room(db: AsyncSession, row: _RoomRow) -> None:
    site = await _site_by_code(db, row.site_code)
    existing = (
        await db.execute(
            select(Room).where(Room.site_id == site.id, Room.code == row.code)
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(Room(site_id=site.id, code=row.code, description=row.description))
    elif row.description is not None:
        existing.description = row.description


async def _persist_vlan(db: AsyncSession, row: _VlanRow) -> None:
    existing = (
        await db.execute(select(Vlan).where(Vlan.vlan_id == row.vlan_id))
    ).scalar_one_or_none()
    if existing is None:
        db.add(Vlan(**row.model_dump()))
    else:
        existing.name = row.name
        if row.description is not None:
            existing.description = row.description
        if row.color is not None:
            existing.color = row.color


async def _persist_subnet(db: AsyncSession, row: _SubnetRow) -> None:
    site = await _site_by_code(db, row.site_code)
    vlan = await _vlan_by_id(db, row.vlan_id)

    data: dict[str, Any] = {
        "cidr": row.cidr,
        "gateway": row.gateway,
        "vlan_id": vlan.id if vlan else None,
        "site_id": site.id,
        "description": row.description,
        "dhcp_enabled": row.dhcp_enabled if row.dhcp_enabled is not None else False,
        "dhcp_range_start": row.dhcp_range_start,
        "dhcp_range_end": row.dhcp_range_end,
    }

    existing = (
        await db.execute(select(Subnet).where(Subnet.cidr == row.cidr))
    ).scalar_one_or_none()
    if existing is None:
        db.add(Subnet(**data))
    else:
        for k, v in data.items():
            if v is not None or k in ("vlan_id", "gateway", "dhcp_range_start", "dhcp_range_end"):
                setattr(existing, k, v)


async def _find_subnet_for(db: AsyncSession, address: str) -> Subnet:
    """Locate the subnet whose CIDR contains the given address — used by the
    `ips` import which omits `subnet_id` from the CSV.

    Postgres-side equivalent would be `WHERE address << subnets.cidr`. Doing
    it in Python is fine: subnet rows are few (< 200) for realistic networks.
    """
    addr = IPv4Address(address)
    rows = (await db.execute(select(Subnet))).scalars().all()
    for s in rows:
        if addr in IPv4Network(s.cidr, strict=False):
            return s
    raise _RefError("address", address, f"No subnet contains {address}")


async def _persist_ip(db: AsyncSession, row: _IpRow) -> None:
    subnet = await _find_subnet_for(db, row.address)
    device = await _device_by_name(db, row.device_name)

    existing = (
        await db.execute(select(Ip).where(Ip.address == row.address))
    ).scalar_one_or_none()
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
        db.add(Ip(**data))
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
    existing = (
        await db.execute(select(Device).where(Device.name == row.name))
    ).scalar_one_or_none()
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
        db.add(Device(**data))
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
    existing = (
        await db.execute(select(Switch).where(Switch.name == row.name))
    ).scalar_one_or_none()
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
        ip_row = (
            await db.execute(select(Ip).where(Ip.address == row.connected_ip))
        ).scalar_one_or_none()
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
            if vlan.id == port.native_vlan_id:
                raise _RefError(
                    "trunk_vlans",
                    vid,
                    f"VLAN {vid} is the native VLAN of this port — cannot also tag it.",
                )
            wanted_ids.append(vlan.id)
        # Drop existing tagged VLANs, then insert the new set.
        existing_pv = (
            await db.execute(select(PortVlan).where(PortVlan.port_id == port.id))
        ).scalars().all()
        for pv in existing_pv:
            await db.delete(pv)
        for vid in wanted_ids:
            db.add(PortVlan(port_id=port.id, vlan_id=vid))


async def _persist_link(db: AsyncSession, row: _LinkRow) -> None:
    sa = await _switch_by_name(db, row.switch_a, column="switch_a")
    sb = await _switch_by_name(db, row.switch_b, column="switch_b")
    pa = await _port_on_switch(db, sa, row.port_a, column="port_a")
    pb = await _port_on_switch(db, sb, row.port_b, column="port_b")

    if pa.id == pb.id:
        raise _RefError("port_a", row.port_a, "Cannot link a port to itself")

    a_id, b_id = (pa.id, pb.id) if pa.id < pb.id else (pb.id, pa.id)

    existing = (
        await db.execute(
            select(Link).where(Link.port_a_id == a_id, Link.port_b_id == b_id)
        )
    ).scalar_one_or_none()

    data = {
        "link_type": row.link_type,
        "speed_mbps": row.speed_mbps,
        "description": row.description,
    }
    if existing is None:
        db.add(Link(port_a_id=a_id, port_b_id=b_id, **data))
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


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #


def _parse_csv(content: bytes) -> list[dict[str, str]]:
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    rows: list[dict[str, str]] = []
    for raw in reader:
        rows.append({(k or "").strip(): (v or "").strip() for k, v in raw.items()})
    return rows


def _format_validation_errors(
    line: int, raw: dict[str, str], exc: ValidationError
) -> list[ImportErrorRow]:
    out: list[ImportErrorRow] = []
    for err in exc.errors():
        loc = err.get("loc", ())
        column = str(loc[0]) if loc else None
        out.append(
            ImportErrorRow(
                line=line,
                column=column,
                value=raw.get(column, "") if column else None,
                error=err.get("msg", "validation error"),
            )
        )
    return out


@dataclass
class _SingleResult:
    """Outcome of importing one CSV without commit/rollback. The caller is
    responsible for committing the surrounding transaction."""

    parsed_rows: int
    ok_rows: int
    error_rows: list[ImportErrorRow]


async def _import_one(
    db: AsyncSession, entity: str, content: bytes
) -> _SingleResult:
    """Parse + validate + flush all rows of one CSV against `db`.

    Does NOT commit or rollback — that's the caller's job. This lets the bulk
    importer chain several CSVs in a single transaction and roll the whole
    thing back if any file fails.
    """
    if entity not in SPECS:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "UNKNOWN_ENTITY",
                    "message": f"Unknown entity {entity!r}. "
                    f"Expected one of: {sorted(SPECS)}.",
                }
            },
        )
    spec = SPECS[entity]

    rows = _parse_csv(content)
    if not rows:
        return _SingleResult(parsed_rows=0, ok_rows=0, error_rows=[])

    # ---- Parse / validate phase ------------------------------------------
    parsed: list[tuple[int, BaseModel, dict[str, str]]] = []
    parse_errors: list[ImportErrorRow] = []
    for i, raw in enumerate(rows, start=2):  # row 1 = header
        try:
            model = spec.row_model.model_validate(raw)
        except ValidationError as exc:
            parse_errors.extend(_format_validation_errors(i, raw, exc))
            continue
        parsed.append((i, model, raw))

    if parse_errors:
        return _SingleResult(
            parsed_rows=len(rows), ok_rows=0, error_rows=parse_errors
        )

    # ---- Apply phase — flush per row to localize errors ------------------
    apply_errors: list[ImportErrorRow] = []
    success_count = 0
    for line, model, _raw in parsed:
        try:
            await spec.persist(db, model)
            await db.flush()
        except _RefError as e:
            apply_errors.append(
                ImportErrorRow(
                    line=line, column=e.column, value=e.value, error=e.message
                )
            )
            break
        except IntegrityError as e:
            apply_errors.append(
                ImportErrorRow(
                    line=line, error=_friendly_integrity(str(getattr(e, "orig", e)))
                )
            )
            break
        except HTTPException as e:
            err_obj = e.detail.get("error", {}) if isinstance(e.detail, dict) else {}
            apply_errors.append(
                ImportErrorRow(
                    line=line,
                    error=str(err_obj.get("message") or err_obj.get("code") or e.detail),
                )
            )
            break
        success_count += 1

    return _SingleResult(
        parsed_rows=len(rows), ok_rows=success_count, error_rows=apply_errors
    )


def apply_column_mapping(content: bytes, mapping: dict[str, str | None]) -> bytes:
    """Rewrite the header row of a CSV in-memory using `{csv_column → canonical}`.

    - A mapping value of `None` (or a value that resolves to the canonical
      name `null`) means "drop this column entirely" — the rest of the
      rows lose that field as well.
    - Headers absent from the mapping are passed through verbatim, which
      is what lets the AI assistant only worry about the columns it
      successfully identified.
    - The CSV is assumed to use the canonical NetForge encoding (`;`
      delimiter, `utf-8-sig`). Mixed delimiters in the same file are not
      supported because the import pipeline doesn't accept them either.

    Returns the rewritten bytes. The original `content` is not mutated.
    """
    if not mapping:
        return content
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text), delimiter=";")
    try:
        headers = next(reader)
    except StopIteration:
        return content
    # Build per-column decisions in original order: either the rewritten
    # name (and we keep the column) or None (and we drop the column from
    # every row below). Decisions stored as a list of (keep, new_name).
    decisions: list[tuple[bool, str | None]] = []
    for h in headers:
        target = mapping.get(h, h) if h in mapping else h
        if target is None:
            decisions.append((False, None))
        else:
            decisions.append((True, str(target)))
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")
    writer.writerow([new_name for keep, new_name in decisions if keep])
    for row in reader:
        # Skip empty trailing lines without breaking — csv emits a `[]` for
        # them.
        if not row:
            writer.writerow([])
            continue
        writer.writerow(
            [
                row[i] if i < len(row) else ""
                for i, (keep, _new_name) in enumerate(decisions)
                if keep
            ]
        )
    return out.getvalue().encode("utf-8-sig")


async def run_import(
    db: AsyncSession,
    entity: str,
    content: bytes,
    dry_run: bool,
    *,
    column_map: dict[str, str | None] | None = None,
) -> ImportReport:
    if column_map:
        content = apply_column_mapping(content, column_map)
    result = await _import_one(db, entity, content)

    if result.error_rows or dry_run:
        await db.rollback()
        return ImportReport(
            parsed_rows=result.parsed_rows,
            ok_rows=result.ok_rows,
            error_rows=result.error_rows,
            applied=False,
        )

    await db.commit()
    return ImportReport(
        parsed_rows=result.parsed_rows,
        ok_rows=result.ok_rows,
        error_rows=[],
        applied=True,
    )


# --------------------------------------------------------------------------- #
# Auto-detection — match CSV headers against each entity's required columns
# to pick the right importer without forcing the user to choose.
# --------------------------------------------------------------------------- #


def _required_headers(model: type[BaseModel]) -> set[str]:
    """Columns that MUST appear in the CSV for this entity.

    Pydantic fields without a default value are required at validation time —
    they're the strongest signal that a CSV belongs to that entity. Optional
    columns (with defaults like `None`) don't have to be present even if the
    importer would accept them, and using them in the match would muddy the
    score.
    """
    out: set[str] = set()
    for name, field in model.model_fields.items():
        if field.is_required():
            out.add(name)
    return out


def _all_headers(model: type[BaseModel]) -> set[str]:
    return set(model.model_fields.keys())


REQUIRED_HEADERS: dict[str, set[str]] = {
    e: _required_headers(spec.row_model) for e, spec in SPECS.items()
}
ALL_HEADERS: dict[str, set[str]] = {
    e: _all_headers(spec.row_model) for e, spec in SPECS.items()
}


def _read_headers(content: bytes) -> list[str]:
    """Return the column names from the first line of the CSV, or [] if the
    file is empty / unreadable."""
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text), delimiter=";")
    try:
        first = next(reader)
    except StopIteration:
        return []
    return [(h or "").strip() for h in first if h is not None]


@dataclass(frozen=True)
class _DetectMatch:
    entity: str
    score: float
    missing_required: list[str]
    unknown: list[str]


def _score_entity(headers: set[str], entity: str) -> _DetectMatch:
    """Score how well `headers` matches the row model of `entity`.

    A perfect match (score == 1.0) means every required header is present and
    no unknown header appears. Any missing required column kills the match
    (score < 1.0); unknown headers cost a little — enough to disambiguate
    between entities that share a required column subset but differ in their
    optional columns.
    """
    required = REQUIRED_HEADERS[entity]
    known = ALL_HEADERS[entity]
    missing = sorted(required - headers)
    unknown = sorted(headers - known)
    if missing:
        # If any required column is missing the file simply isn't this entity.
        return _DetectMatch(entity, 0.0, missing, unknown)
    # All required columns present. Penalize unknown headers but only mildly,
    # since CSVs from older exports might carry extra columns we now ignore.
    penalty = 0.1 * len(unknown) / max(len(known), 1)
    return _DetectMatch(entity, max(0.0, 1.0 - penalty), [], unknown)


def detect_entity(content: bytes) -> DetectReport:
    """Pick the most likely entity for a CSV by looking at its header row.

    Returns the best match plus diagnostics so the UI can explain *why* a
    file was assigned (or rejected). When several entities tie on required
    columns, the one with the smallest set of unknown headers wins.
    """
    header_list = _read_headers(content)
    headers = set(header_list)

    if not headers:
        return DetectReport(
            entity=None,
            confidence=0.0,
            headers=[],
            matched_required=[],
            missing_required=[],
            unknown_headers=[],
            candidates={},
        )

    scores = {e: _score_entity(headers, e) for e in SPECS}
    # Strict matches first: required columns satisfied. Tie-break by fewest
    # unknown columns, then by entity name for determinism.
    strict = [m for m in scores.values() if not m.missing_required]
    if strict:
        strict.sort(key=lambda m: (len(m.unknown), m.entity))
        best = strict[0]
        return DetectReport(
            entity=best.entity,
            confidence=best.score,
            headers=header_list,
            matched_required=sorted(REQUIRED_HEADERS[best.entity]),
            missing_required=[],
            unknown_headers=best.unknown,
            candidates={e: scores[e].score for e in SPECS},
        )

    # No entity has all its required columns — pick the closest as the most
    # likely intent so the UI can show "did you mean …?" with the missing
    # columns spelled out.
    nearest = min(scores.values(), key=lambda m: (len(m.missing_required), m.entity))
    return DetectReport(
        entity=None,
        confidence=0.0,
        headers=header_list,
        matched_required=sorted(REQUIRED_HEADERS[nearest.entity] & headers),
        missing_required=nearest.missing_required,
        unknown_headers=nearest.unknown,
        candidates={e: scores[e].score for e in SPECS},
    )


# --------------------------------------------------------------------------- #
# Bulk import — multiple CSVs (or a ZIP of CSVs) in a single transaction.
# --------------------------------------------------------------------------- #


# Hard caps to keep memory + transaction time bounded. Tuned so a full
# round-trip of `/api/exports/all` always fits.
BULK_MAX_FILES = 50
BULK_MAX_TOTAL_BYTES = 50 * 1024 * 1024  # 50 MiB total across all CSVs
ZIP_MAX_UNCOMPRESSED = 50 * 1024 * 1024  # guard against zip bombs


def extract_zip(content: bytes) -> list[tuple[str, bytes]]:
    """Pull every .csv member out of a ZIP archive.

    Rejects anything that would expand beyond `ZIP_MAX_UNCOMPRESSED` — defends
    against zip bombs without forcing us to disk-spool. Non-CSV members are
    silently skipped (a backup ZIP may legitimately contain a README).
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "BAD_ZIP",
                    "message": f"ZIP archive is invalid: {exc}",
                }
            },
        ) from exc

    total = 0
    out: list[tuple[str, bytes]] = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        name = info.filename.rsplit("/", 1)[-1]
        if not name.lower().endswith(".csv"):
            continue
        total += info.file_size
        if total > ZIP_MAX_UNCOMPRESSED:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "code": "ZIP_TOO_LARGE",
                        "message": (
                            f"ZIP expands to more than "
                            f"{ZIP_MAX_UNCOMPRESSED} bytes uncompressed."
                        ),
                    }
                },
            )
        with zf.open(info, "r") as fh:
            out.append((name, fh.read()))
    return out


async def run_bulk_import(
    db: AsyncSession,
    files: list[tuple[str, bytes]],
    dry_run: bool,
) -> BulkImportReport:
    """Detect → order → apply, all inside a single transaction.

    Any file failure aborts the whole batch. `dry_run=True` always rolls back
    even if every file would have applied cleanly. Reports are per-file so
    the UI can pinpoint which CSV caused the rollback.
    """
    if not files:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "NO_FILES",
                    "message": "No CSV file supplied.",
                }
            },
        )
    if len(files) > BULK_MAX_FILES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "TOO_MANY_FILES",
                    "message": (
                        f"At most {BULK_MAX_FILES} files per bulk import "
                        f"(got {len(files)})."
                    ),
                }
            },
        )
    total_bytes = sum(len(c) for _, c in files)
    if total_bytes > BULK_MAX_TOTAL_BYTES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "BULK_TOO_LARGE",
                    "message": (
                        f"Total upload size {total_bytes} exceeds the "
                        f"{BULK_MAX_TOTAL_BYTES} byte bulk limit."
                    ),
                }
            },
        )

    # ---- Phase 1: detect entity for every file ---------------------------
    detections: list[tuple[str, bytes, DetectReport]] = []
    file_reports: list[BulkImportFileReport] = []
    any_detect_error = False
    for filename, content in files:
        det = detect_entity(content)
        if det.entity is None:
            any_detect_error = True
            file_reports.append(
                BulkImportFileReport(
                    filename=filename,
                    detected_entity=None,
                    parsed_rows=0,
                    ok_rows=0,
                    error_rows=[
                        ImportErrorRow(
                            line=1,
                            column=None,
                            value=None,
                            error=(
                                "Could not detect the entity from the header row. "
                                + (
                                    f"Closest match would need columns: "
                                    f"{', '.join(det.missing_required)}."
                                    if det.missing_required
                                    else "Header row is empty."
                                )
                            ),
                        )
                    ],
                )
            )
        else:
            detections.append((filename, content, det))

    if any_detect_error:
        # Don't even start the transaction — surface every file we couldn't
        # route so the user can fix all of them at once.
        for filename, _, det in detections:
            file_reports.append(
                BulkImportFileReport(
                    filename=filename,
                    detected_entity=det.entity,
                    parsed_rows=0,
                    ok_rows=0,
                    error_rows=[],
                )
            )
        return BulkImportReport(
            files=_sort_bulk_reports(file_reports),
            total_parsed_rows=0,
            total_ok_rows=0,
            applied=False,
        )

    # ---- Phase 2: apply in dependency order ------------------------------
    detections.sort(key=lambda t: IMPORT_ORDER.index(t[2].entity))  # type: ignore[arg-type]

    total_parsed = 0
    total_ok = 0
    had_error = False
    for filename, content, det in detections:
        assert det.entity is not None  # phase 1 filtered the Nones out
        result = await _import_one(db, det.entity, content)
        total_parsed += result.parsed_rows
        total_ok += result.ok_rows
        file_reports.append(
            BulkImportFileReport(
                filename=filename,
                detected_entity=det.entity,
                parsed_rows=result.parsed_rows,
                ok_rows=result.ok_rows,
                error_rows=result.error_rows,
            )
        )
        if result.error_rows:
            had_error = True
            break

    # Files we skipped after the first failure still get reported so the UI
    # can show "pending" rather than silently dropping them.
    seen = {fr.filename for fr in file_reports}
    for filename, _, det in detections:
        if filename in seen:
            continue
        file_reports.append(
            BulkImportFileReport(
                filename=filename,
                detected_entity=det.entity,
                parsed_rows=0,
                ok_rows=0,
                error_rows=[],
            )
        )

    if had_error or dry_run:
        await db.rollback()
        return BulkImportReport(
            files=_sort_bulk_reports(file_reports),
            total_parsed_rows=total_parsed,
            total_ok_rows=total_ok,
            applied=False,
        )

    await db.commit()
    return BulkImportReport(
        files=_sort_bulk_reports(file_reports),
        total_parsed_rows=total_parsed,
        total_ok_rows=total_ok,
        applied=True,
    )


def _sort_bulk_reports(reports: list[BulkImportFileReport]) -> list[BulkImportFileReport]:
    """Stable display order: detected files in dependency order, then any
    undetected file (kept at the end so they're visually grouped)."""

    def key(r: BulkImportFileReport) -> tuple[int, str]:
        if r.detected_entity is None:
            return (len(IMPORT_ORDER), r.filename)
        return (IMPORT_ORDER.index(r.detected_entity), r.filename)

    return sorted(reports, key=key)


def _friendly_integrity(msg: str) -> str:
    """Surface the underlying DB constraint name without leaking the full
    SQLAlchemy traceback to the API caller."""
    for hint, friendly in (
        ("subnets_no_overlap", "CIDR overlaps an existing subnet"),
        ("sites_code_key", "site code already exists"),
        ("rooms_site_code_uniq", "room code already exists in this site"),
        ("vlans_vlan_id_key", "VLAN id already exists"),
        ("ips_address_key", "IP address already exists"),
        ("switches_name_key", "switch name already exists"),
        ("ports_switch_number_uniq", "port number already exists on this switch"),
        ("links_ports_uniq", "link between these two ports already exists"),
        ("ips_check_in_subnet", "IP is not contained in any registered subnet"),
    ):
        if hint in msg:
            return friendly
    return "database constraint violation"
