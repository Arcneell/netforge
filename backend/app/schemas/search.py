"""Global search response."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class SearchResult(BaseModel):
    type: Literal["ip", "device", "switch", "port"]
    id: int
    label: str
    context: str | None = None


class SearchResponse(BaseModel):
    results: list[SearchResult]
