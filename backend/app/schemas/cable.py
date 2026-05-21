"""Cable — request/response schemas."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class CableBase(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    link_id: int | None = Field(default=None, gt=0)
    length_m: int | None = Field(default=None, ge=0, le=10_000)
    color: str | None = Field(default=None, max_length=40)
    vendor: str | None = Field(default=None, max_length=100)
    part_number: str | None = Field(default=None, max_length=100)
    serial: str | None = Field(default=None, max_length=120)
    installed_on: date | None = None
    last_tested_on: date | None = None
    notes: str | None = None


class CableCreate(CableBase):
    pass


class CableUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    link_id: int | None = Field(default=None, gt=0)
    length_m: int | None = Field(default=None, ge=0, le=10_000)
    color: str | None = Field(default=None, max_length=40)
    vendor: str | None = Field(default=None, max_length=100)
    part_number: str | None = Field(default=None, max_length=100)
    serial: str | None = Field(default=None, max_length=120)
    installed_on: date | None = None
    last_tested_on: date | None = None
    notes: str | None = None


class CableRead(CableBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime
