"""Subnets — IPv4 CIDR blocks."""

from __future__ import annotations

from datetime import datetime
from ipaddress import IPv4Address, IPv4Network

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _to_str_v4_network(value: str | IPv4Network) -> str:
    """Parse the value as an IPv4 network and re-serialize in canonical form."""
    network = value if isinstance(value, IPv4Network) else IPv4Network(value, strict=False)
    return str(network)


def _to_str_v4_address(value: str | IPv4Address | None) -> str | None:
    if value is None:
        return None
    return str(value if isinstance(value, IPv4Address) else IPv4Address(value))


class SubnetBase(BaseModel):
    cidr: str = Field(description="IPv4 CIDR, e.g. 10.0.30.0/24")
    gateway: str | None = None
    vlan_id: int | None = Field(default=None, gt=0)
    site_id: int = Field(gt=0)
    description: str | None = None
    dhcp_enabled: bool = False
    dhcp_range_start: str | None = None
    dhcp_range_end: str | None = None

    @field_validator("cidr", mode="before")
    @classmethod
    def _validate_cidr(cls, v: object) -> str:
        return _to_str_v4_network(v)  # type: ignore[arg-type]

    @field_validator("gateway", "dhcp_range_start", "dhcp_range_end", mode="before")
    @classmethod
    def _validate_address(cls, v: object) -> str | None:
        return _to_str_v4_address(v)  # type: ignore[arg-type]


class SubnetCreate(SubnetBase):
    pass


class SubnetUpdate(BaseModel):
    cidr: str | None = None
    gateway: str | None = None
    vlan_id: int | None = Field(default=None, gt=0)
    site_id: int | None = Field(default=None, gt=0)
    description: str | None = None
    dhcp_enabled: bool | None = None
    dhcp_range_start: str | None = None
    dhcp_range_end: str | None = None

    @field_validator("cidr", mode="before")
    @classmethod
    def _validate_cidr(cls, v: object) -> str | None:
        if v is None:
            return None
        return _to_str_v4_network(v)  # type: ignore[arg-type]

    @field_validator("gateway", "dhcp_range_start", "dhcp_range_end", mode="before")
    @classmethod
    def _validate_address(cls, v: object) -> str | None:
        return _to_str_v4_address(v)  # type: ignore[arg-type]


class SubnetRead(SubnetBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime
