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


class BulkIpAction(str, Enum):
    reserve = "reserve"
    release = "release"


class BulkIpRange(BaseModel):
    """Bulk-operate on a contiguous range of host addresses inside a subnet.

    - `reserve` creates an IP row per address with the given status, skipping
      any address that already has a row (unless `overwrite=True`, in which
      case the existing row is updated in place).
    - `release` deletes every IP row whose address falls in the range.
    Capped server-side so a malformed range can't trigger a runaway
    transaction.
    """

    action: BulkIpAction
    start: str
    end: str
    # Defaults to `reserved` — the most common bulk use case is parking a
    # range for a vendor / DHCP exclusion / planned hardware. `assigned`
    # is the second most common (label imports).
    status: IpStatus = IpStatus.reserved
    overwrite: bool = False
    description: str | None = Field(default=None, max_length=500)

    @field_validator("start", "end", mode="before")
    @classmethod
    def _validate_addr(cls, v: object) -> str:
        return str(IPv4Address(v))  # type: ignore[arg-type]


class BulkIpResult(BaseModel):
    """Summary returned by `POST /api/subnets/{id}/bulk-ip`."""

    requested: int
    created: int
    updated: int
    deleted: int
    skipped: int
