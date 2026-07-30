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
    site_id: int | None = Query(
        default=None, gt=0, description="Restrict to switches and devices in this site."
    ),
    room_id: int | None = Query(
        default=None, gt=0, description="Restrict to a single room."
    ),
    vlan_id: int | None = Query(
        default=None,
        gt=0,
        description=(
            "Keep only switches carrying this VLAN (native or tagged) on at "
            "least one port. Links between those switches are all returned — "
            "filtering edges too would hide the cable carrying the VLAN."
        ),
    ),
    include_devices: bool = Query(
        default=True,
        description=(
            "Include non-switch devices as leaf nodes, with an `attachment` "
            "edge per port they are plugged into. Turn off for a "
            "switch-only backbone view."
        ),
    ),
    db: AsyncSession = Depends(get_db),
) -> TopologyResponse:
    return await service.build_topology(
        db,
        site_id=site_id,
        room_id=room_id,
        vlan_id=vlan_id,
        include_devices=include_devices,
    )
