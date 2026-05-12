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


class LinkCreateByName(BaseModel):
    """Create a link by (switch name, port number) — what the topology UI
    actually has on hand. The service resolves the two endpoints to port ids
    and delegates to the standard create path.

    Kept separate from `LinkCreate` so the existing IDs-only contract and its
    tests are untouched, and CSV import / scripted callers can keep using
    whichever shape is most convenient.
    """

    switch_a: str = Field(min_length=1, max_length=100)
    port_a: int = Field(gt=0)
    switch_b: str = Field(min_length=1, max_length=100)
    port_b: int = Field(gt=0)
    link_type: LinkType
    speed_mbps: int | None = Field(default=None, gt=0)
    description: str | None = None

    @model_validator(mode="after")
    def _endpoints_must_differ(self) -> LinkCreateByName:
        if self.switch_a == self.switch_b and self.port_a == self.port_b:
            raise ValueError("the two endpoints must differ")
        return self


class LinkUpdate(BaseModel):
    """Only metadata is mutable here. Changing which ports a link connects is
    *not* an update — delete the link and recreate it. This mirrors the way
    the underlying `(port_a_id, port_b_id)` tuple is the unique key in the DB,
    so an "update the ports" PUT would actually be a replace from the DB's
    point of view."""

    link_type: LinkType | None = None
    speed_mbps: int | None = Field(default=None, gt=0)
    description: str | None = None


class LinkRead(LinkBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
