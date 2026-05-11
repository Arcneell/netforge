"""Rooms — wiring closets / server rooms inside a site."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RoomBase(BaseModel):
    site_id: int = Field(gt=0)
    code: str = Field(min_length=1, max_length=50)
    description: str | None = None


class RoomCreate(RoomBase):
    pass


class RoomUpdate(BaseModel):
    site_id: int | None = Field(default=None, gt=0)
    code: str | None = Field(default=None, min_length=1, max_length=50)
    description: str | None = None


class RoomRead(RoomBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
