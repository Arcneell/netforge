"""Switches."""

from __future__ import annotations

from datetime import date, datetime
from ipaddress import IPv4Address

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _addr_or_none(v: object | None) -> str | None:
    return None if v is None else str(IPv4Address(v))  # type: ignore[arg-type]


class SwitchBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    vendor: str | None = Field(default=None, max_length=50)
    model: str | None = Field(default=None, max_length=100)
    serial: str | None = Field(default=None, max_length=100)
    management_ip: str | None = None
    room_id: int | None = Field(default=None, gt=0)
    rack_position: str | None = Field(default=None, max_length=20)
    port_count: int = Field(gt=0, le=1024)
    firmware_version: str | None = Field(default=None, max_length=50)
    snmp_community: str | None = Field(default=None, max_length=100)
    asset_tag: str | None = Field(default=None, max_length=50)
    warranty_expires_at: date | None = None
    eol_date: date | None = None
    description: str | None = None

    @field_validator("management_ip", mode="before")
    @classmethod
    def _validate_ip(cls, v: object) -> str | None:
        return _addr_or_none(v)


class SwitchCreate(SwitchBase):
    pass


class SwitchUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    vendor: str | None = Field(default=None, max_length=50)
    model: str | None = Field(default=None, max_length=100)
    serial: str | None = Field(default=None, max_length=100)
    management_ip: str | None = None
    room_id: int | None = Field(default=None, gt=0)
    rack_position: str | None = Field(default=None, max_length=20)
    # port_count is intentionally NOT updatable here — adding/removing ports
    # in bulk would silently destroy port references on links/VLANs.
    firmware_version: str | None = Field(default=None, max_length=50)
    snmp_community: str | None = Field(default=None, max_length=100)
    asset_tag: str | None = Field(default=None, max_length=50)
    warranty_expires_at: date | None = None
    eol_date: date | None = None
    description: str | None = None

    @field_validator("management_ip", mode="before")
    @classmethod
    def _validate_ip(cls, v: object) -> str | None:
        return _addr_or_none(v)


class SwitchRead(SwitchBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime
