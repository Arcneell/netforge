"""Global search response."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class SearchResult(BaseModel):
    type: Literal[
        "ip",
        "device",
        "switch",
        "port",
        "site",
        "room",
        "vlan",
        "subnet",
    ]
    id: int
    label: str
    context: str | None = None
    # Owner needed to route to a useful page: IP → subnet detail,
    # port → switch detail. Devices, switches, VLANs and subnets are routed
    # directly by `id` (or by listing page), so this stays None for those.
    parent_id: int | None = None


class SearchResponse(BaseModel):
    results: list[SearchResult]
