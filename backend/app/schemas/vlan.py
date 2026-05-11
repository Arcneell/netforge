"""VLANs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class VlanBase(BaseModel):
    vlan_id: int = Field(ge=1, le=4094)
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class VlanCreate(VlanBase):
    pass


class VlanUpdate(BaseModel):
    vlan_id: int | None = Field(default=None, ge=1, le=4094)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class VlanRead(VlanBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
