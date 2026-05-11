"""Shared schemas and helpers reused by every CRUD router.

- `Page[T]` — list response envelope `{ items, total, page, page_size }`
- `PageParams` — FastAPI dependency for `?page=&page_size=`
- `ErrorDetail` / `ErrorResponse` — uniform error body `{ error: { code, message, details? } }`
"""

from __future__ import annotations

from typing import Annotated, Any, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class PageParams:
    """`?page=1&page_size=50` query parameters."""

    def __init__(
        self,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> None:
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
