"""IP addresses."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from ipaddress import IPv4Address

from pydantic import BaseModel, ConfigDict, Field, field_validator


class IpStatus(str, Enum):
    reserved = "reserved"
    assigned = "assigned"
    dhcp = "dhcp"


class IpBase(BaseModel):
    subnet_id: int = Field(gt=0)
    address: str = Field(description="IPv4 address, e.g. 10.0.30.42")
    hostname: str | None = Field(default=None, max_length=255)
    mac: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$")
    device_id: int | None = Field(default=None, gt=0)
    status: IpStatus
    description: str | None = None

    @field_validator("address", mode="before")
    @classmethod
    def _validate_address(cls, v: object) -> str:
        return str(IPv4Address(v))  # type: ignore[arg-type]


class IpCreate(IpBase):
    pass


class IpUpdate(BaseModel):
    subnet_id: int | None = Field(default=None, gt=0)
    address: str | None = None
    hostname: str | None = Field(default=None, max_length=255)
    mac: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$")
    device_id: int | None = Field(default=None, gt=0)
    status: IpStatus | None = None
    description: str | None = None

    @field_validator("address", mode="before")
    @classmethod
    def _validate_address(cls, v: object) -> str | None:
        if v is None:
            return None
        return str(IPv4Address(v))  # type: ignore[arg-type]


class IpRead(IpBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime
