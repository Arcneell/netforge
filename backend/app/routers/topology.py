"""Topology graph — /api/topology."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db import get_session as get_db
from app.schemas.topology import TopologyResponse
from app.services import topology as service

router = APIRouter(prefix="/topology", tags=["topology"])


@router.get(
    "", response_model=TopologyResponse, dependencies=[Depends(get_current_user)]
)
async def get_topology(
    site_id: int | None = Query(default=None, gt=0),
    db: AsyncSession = Depends(get_db),
) -> TopologyResponse:
    return await service.build_topology(db, site_id=site_id)
