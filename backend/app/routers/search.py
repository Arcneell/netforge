"""Global search — /api/search."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db import get_session as get_db
from app.schemas.search import SearchResponse
from app.services import search as service

router = APIRouter(prefix="/search", tags=["search"])


@router.get(
    "", response_model=SearchResponse, dependencies=[Depends(get_current_user)]
)
async def global_search(
    q: str = Query(min_length=1, max_length=120),
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    results = await service.search(db, q)
    return SearchResponse(results=results)
