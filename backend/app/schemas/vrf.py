"""VRF — request/response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class VrfBase(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    rd: str | None = Field(default=None, max_length=32)
    description: str | None = None


class VrfCreate(VrfBase):
    pass


class VrfUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    rd: str | None = Field(default=None, max_length=32)
    description: str | None = None


class VrfRead(VrfBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime
