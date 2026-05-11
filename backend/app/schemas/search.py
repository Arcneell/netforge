"""Global search response."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class SearchResult(BaseModel):
    type: Literal["ip", "device", "switch", "port"]
    id: int
    label: str
    context: str | None = None
    # Owner needed to route to a useful page: IP → subnet detail,
    # port → switch detail. Devices and switches are routed by `id`,
    # so this stays None for those types.
    parent_id: int | None = None


class SearchResponse(BaseModel):
    results: list[SearchResult]
