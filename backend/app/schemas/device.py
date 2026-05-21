"""Devices — anything that's not a switch (servers, phones, APs, ...)."""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class DeviceType(str, Enum):
    server = "server"
    desktop = "desktop"
    laptop = "laptop"
    printer = "printer"
    phone = "phone"
    ap = "ap"
    camera = "camera"
    ups = "ups"
    other = "other"


class DeviceBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    type: DeviceType
    vendor: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    serial: str | None = Field(default=None, max_length=100)
    room_id: int | None = Field(default=None, gt=0)
    asset_tag: str | None = Field(default=None, max_length=50)
    warranty_expires_at: date | None = None
    eol_date: date | None = None
    description: str | None = None


class DeviceCreate(DeviceBase):
    pass


class DeviceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    type: DeviceType | None = None
    vendor: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    serial: str | None = Field(default=None, max_length=100)
    room_id: int | None = Field(default=None, gt=0)
    asset_tag: str | None = Field(default=None, max_length=50)
    warranty_expires_at: date | None = None
    eol_date: date | None = None
    description: str | None = None


class DeviceRead(DeviceBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
