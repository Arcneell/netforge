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
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network
from typing import Any, Awaitable, Callable

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
from app.schemas.imports import ImportErrorRow, ImportReport


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
    def _both_or_neither_location(self) -> "_SwitchRow":
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


async def run_import(
    db: AsyncSession, entity: str, content: bytes, dry_run: bool
) -> ImportReport:
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
        return ImportReport(parsed_rows=0, ok_rows=0, error_rows=[], applied=False)

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
        return ImportReport(
            parsed_rows=len(rows),
            ok_rows=0,
            error_rows=parse_errors,
            applied=False,
        )

    # ---- Apply phase — one transaction, flush per row to localize errors -
    apply_errors: list[ImportErrorRow] = []
    # Tracks rows successfully persisted before any failure aborts the loop.
    # `len(parsed) - len(apply_errors)` would be wrong: it'd credit rows we
    # never even attempted because we `break` on first failure.
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

    if apply_errors or dry_run:
        await db.rollback()
        return ImportReport(
            parsed_rows=len(rows),
            ok_rows=success_count,
            error_rows=apply_errors,
            applied=False,
        )

    await db.commit()
    return ImportReport(
        parsed_rows=len(rows),
        ok_rows=len(parsed),
        error_rows=[],
        applied=True,
    )


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
