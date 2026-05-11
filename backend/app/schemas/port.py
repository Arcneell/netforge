"""Switch ports."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class PortMode(str, Enum):
    access = "access"
    trunk = "trunk"
    hybrid = "hybrid"
    disabled = "disabled"


class PortAdminStatus(str, Enum):
    up = "up"
    down = "down"


class PortBase(BaseModel):
    switch_id: int = Field(gt=0)
    number: int = Field(gt=0)
    label: str | None = Field(default=None, max_length=100)
    mode: PortMode = PortMode.access
    native_vlan_id: int | None = Field(default=None, gt=0)
    admin_status: PortAdminStatus = PortAdminStatus.up
    connected_device_id: int | None = Field(default=None, gt=0)
    connected_ip_id: int | None = Field(default=None, gt=0)
    notes: str | None = None


class PortUpdate(BaseModel):
    """All editable fields. `switch_id` and `number` are immutable here —
    ports are created automatically with their switch."""

    label: str | None = Field(default=None, max_length=100)
    mode: PortMode | None = None
    native_vlan_id: int | None = Field(default=None, gt=0)
    admin_status: PortAdminStatus | None = None
    connected_device_id: int | None = Field(default=None, gt=0)
    connected_ip_id: int | None = Field(default=None, gt=0)
    notes: str | None = None


class PortRead(PortBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


class TaggedVlanAdd(BaseModel):
    vlan_id: int = Field(gt=0)
