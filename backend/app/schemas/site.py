"""Sites — physical locations (HQ, branch, datacenter)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SiteBase(BaseModel):
    code: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=200)
    address: str | None = None


class SiteCreate(SiteBase):
    pass


class SiteUpdate(BaseModel):
    code: str | None = Field(
        default=None, min_length=1, max_length=20, pattern=r"^[A-Za-z0-9_-]+$"
    )
    name: str | None = Field(default=None, min_length=1, max_length=200)
    address: str | None = None


class SiteRead(SiteBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime
