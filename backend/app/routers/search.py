"""Global search — /api/search."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db import get_session as get_db
from app.schemas.search import SearchResponse
from app.services import search as service
from app.services.read_cache import cached_read

router = APIRouter(prefix="/search", tags=["search"])

_RESPONSE_ADAPTER = TypeAdapter(SearchResponse)


async def _run_search(db: AsyncSession, q: str) -> SearchResponse:
    return SearchResponse(results=await service.search(db, q))


@router.get(
    "", response_model=SearchResponse, dependencies=[Depends(get_current_user)]
)
async def global_search(
    q: str = Query(min_length=1, max_length=120),
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    # One bounded query per entity type (seven) for a term the operator is
    # still typing — the repeat rate on a search box is exactly what a cache
    # is for. No-op without REDIS_URL.
    return await cached_read(
        db,
        name="search",
        params={"q": q},
        adapter=_RESPONSE_ADAPTER,
        builder=lambda: _run_search(db, q),
    )
