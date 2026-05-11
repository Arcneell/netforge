"""Physical links between two switch ports."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LinkType(str, Enum):
    copper = "copper"
    fiber = "fiber"
    dac = "dac"
    virtual = "virtual"


class LinkBase(BaseModel):
    port_a_id: int = Field(gt=0)
    port_b_id: int = Field(gt=0)
    link_type: LinkType
    speed_mbps: int | None = Field(default=None, gt=0)
    description: str | None = None

    @model_validator(mode="after")
    def _ports_must_differ(self) -> LinkBase:
        if self.port_a_id == self.port_b_id:
            raise ValueError("port_a_id and port_b_id must differ")
        return self


class LinkCreate(LinkBase):
    pass


class LinkRead(LinkBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
