"""Row models — one Pydantic class per entity, mapping the CSV column names.

Each `_*Row` docstring documents the natural key used by the matching
`_persist_*` function; the field validators document the blank-cell coercions
that keep `export → import` round-trips lossless.
"""

from __future__ import annotations

import re
from ipaddress import IPv4Address, IPv4Network
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.device import DeviceType
from app.models.ip import IpStatus
from app.models.link import LinkType
from app.models.port import PortAdminStatus, PortMode


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
