"""Subnets router — /api/subnets."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.db import get_session as get_db
from app.models.user import UserRole
from app.schemas.common import Page, PageParams
from app.schemas.ip import BulkIpRange, BulkIpResult
from app.schemas.subnet import (
    NextFreeIpResponse,
    SubnetCapacityOverview,
    SubnetCreate,
    SubnetIpsResponse,
    SubnetRead,
    SubnetTreeNode,
    SubnetUpdate,
    SubnetUtilization,
)
from app.services import ips as ips_service
from app.services import subnets as service
from app.services.read_cache import cached_read

router = APIRouter(prefix="/subnets", tags=["subnets"])

# Built once — see the note in `routers/topology.py`. The tree endpoint answers
# with a bare list, which is why these go through `TypeAdapter` rather than the
# response models' own `model_validate`.
_TREE_ADAPTER = TypeAdapter(list[SubnetTreeNode])
_CAPACITY_ADAPTER = TypeAdapter(SubnetCapacityOverview)


@router.get("", response_model=Page[SubnetRead], dependencies=[Depends(get_current_user)])
async def list_subnets(
    page: PageParams = Depends(),
    site_id: int | None = Query(default=None, gt=0),
    vlan_id: int | None = Query(default=None, gt=0),
    vrf_id: int | None = Query(
        default=None,
        ge=0,
        description="Filter by VRF. Use `0` to fetch only global-scope subnets.",
    ),
    q: str | None = Query(
        default=None,
        min_length=1,
        max_length=120,
        description="Free-text search over CIDR + description (trigram-indexed).",
    ),
    db: AsyncSession = Depends(get_db),
) -> Page[SubnetRead]:
    items, total, ip_counts = await service.list_subnets(
        db, page, site_id=site_id, vlan_id=vlan_id, vrf_id=vrf_id, q=q
    )
    return Page[SubnetRead](
        items=[
            SubnetRead.model_validate(s).model_copy(
                update={
                    "usable": service.usable_hosts(str(s.cidr)),
                    "used": ip_counts.get(s.id, 0),
                }
            )
            for s in items
        ],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get(
    "/tree",
    response_model=list[SubnetTreeNode],
    dependencies=[Depends(get_current_user)],
)
async def subnet_tree(
    vrf_id: int | None = Query(
        default=None,
        ge=0,
        description="VRF scope. Omit or pass `0` for the global VRF.",
    ),
    site_id: int | None = Query(
        default=None,
        gt=0,
        description="Filter the tree to a single site.",
    ),
    vlan_id: int | None = Query(
        default=None,
        gt=0,
        description="Filter the tree to a single VLAN.",
    ),
    auto_group_prefix: int = Query(
        default=16,
        ge=0,
        le=31,
        description=(
            "Wrap flat root subnets sharing a /N supernet under a synthetic "
            "virtual parent so the tree shows real hierarchy. Pass `0` to "
            "disable and get the raw flat list of roots."
        ),
    ),
    db: AsyncSession = Depends(get_db),
) -> list[SubnetTreeNode]:
    """Hierarchical view of the subnets in one VRF. Roots first, depth-first
    children. Operators with no VRFs configured just see the global tree.

    `site_id` / `vlan_id` narrow the result client-side without changing
    the hierarchy — orphaned matches float up to root level so a filter
    on a leaf VLAN still surfaces the matching subnets even when their
    parents were dropped."""
    # The service treats None as "global" but the OpenAPI `Query(ge=0)`
    # accepts a literal 0 too — normalise here.
    scope = None if vrf_id in (None, 0) else vrf_id

    async def _build() -> list[SubnetTreeNode]:
        raw = await service.build_subnet_tree(
            db,
            scope,
            auto_group_prefix=auto_group_prefix or None,
            site_id=site_id,
            vlan_id=vlan_id,
        )
        return [SubnetTreeNode.model_validate(n) for n in raw]

    # Fetches every in-scope subnet and assembles the hierarchy in Python, so
    # it is worth caching when Redis is configured. Keyed on a fingerprint of
    # the inventory (see services/read_cache.py), never on invalidation.
    return await cached_read(
        db,
        name="subnet_tree",
        params={
            "vrf_id": scope,
            "site_id": site_id,
            "vlan_id": vlan_id,
            "auto_group_prefix": auto_group_prefix,
        },
        adapter=_TREE_ADAPTER,
        builder=_build,
    )


@router.get(
    "/capacity-overview",
    response_model=SubnetCapacityOverview,
    dependencies=[Depends(get_current_user)],
)
async def capacity_overview(
    limit: int = Query(
        default=5,
        ge=1,
        le=20,
        description="Maximum entries per ranked bucket. Default 5.",
    ),
    db: AsyncSession = Depends(get_db),
) -> SubnetCapacityOverview:
    """Top-N subnet rankings for the dashboard: fullest, at-capacity, unused.

    Declared BEFORE `/{subnet_id}` so the literal path wins the route match
    — otherwise FastAPI would try to coerce `"capacity-overview"` to int and
    surface a 422.
    """
    async def _build() -> SubnetCapacityOverview:
        data = await service.capacity_overview(db, limit=limit)
        return SubnetCapacityOverview.model_validate(data)

    # Dashboard widget: hit on every landing-page load, aggregates the whole
    # subnet scope. Cached when Redis is configured.
    return await cached_read(
        db,
        name="subnet_capacity",
        params={"limit": limit},
        adapter=_CAPACITY_ADAPTER,
        builder=_build,
    )


@router.get(
    "/{subnet_id}", response_model=SubnetRead, dependencies=[Depends(get_current_user)]
)
async def get_subnet(subnet_id: int, db: AsyncSession = Depends(get_db)) -> SubnetRead:
    subnet = await service.get_subnet(db, subnet_id)
    return SubnetRead.model_validate(subnet)


@router.post(
    "",
    response_model=SubnetRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def create_subnet(
    payload: SubnetCreate, db: AsyncSession = Depends(get_db)
) -> SubnetRead:
    subnet = await service.create_subnet(db, payload)
    return SubnetRead.model_validate(subnet)


@router.put(
    "/{subnet_id}",
    response_model=SubnetRead,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def update_subnet(
    subnet_id: int, payload: SubnetUpdate, db: AsyncSession = Depends(get_db)
) -> SubnetRead:
    subnet = await service.update_subnet(db, subnet_id, payload)
    return SubnetRead.model_validate(subnet)


@router.delete(
    "/{subnet_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def delete_subnet(subnet_id: int, db: AsyncSession = Depends(get_db)) -> None:
    await service.delete_subnet(db, subnet_id)


# --- Phase 4 utility endpoints -----------------------------------------------


@router.get(
    "/{subnet_id}/ips",
    response_model=SubnetIpsResponse,
    dependencies=[Depends(get_current_user)],
)
async def list_subnet_ips(
    subnet_id: int, db: AsyncSession = Depends(get_db)
) -> SubnetIpsResponse:
    subnet, ips = await service.list_subnet_ips(db, subnet_id)
    return SubnetIpsResponse(subnet=SubnetRead.model_validate(subnet), ips=ips)


@router.post(
    "/{subnet_id}/next-free",
    response_model=NextFreeIpResponse,
    dependencies=[Depends(get_current_user)],
)
async def next_free_ip(
    subnet_id: int, db: AsyncSession = Depends(get_db)
) -> NextFreeIpResponse:
    address = await service.next_free_ip(db, subnet_id)
    return NextFreeIpResponse(address=address)


@router.post(
    "/{subnet_id}/bulk-ip",
    response_model=BulkIpResult,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def bulk_ip_range(
    subnet_id: int,
    payload: BulkIpRange,
    db: AsyncSession = Depends(get_db),
) -> BulkIpResult:
    """Reserve or release every host address in `[start, end]` in one call.

    Admin-only — same gate as single-IP CRUD. Capped at 512 addresses per
    call; larger sweeps must be split client-side. Skips network /
    broadcast slots automatically so the result stays consistent with
    `_per_subnet_used_counts` accounting.
    """
    summary = await ips_service.bulk_ip_range(db, subnet_id, payload)
    return BulkIpResult.model_validate(summary)


@router.get(
    "/{subnet_id}/utilization",
    response_model=SubnetUtilization,
    dependencies=[Depends(get_current_user)],
)
async def subnet_utilization(
    subnet_id: int, db: AsyncSession = Depends(get_db)
) -> SubnetUtilization:
    """Fill-rate snapshot for one subnet. Two SELECTs, works on any prefix
    length — unlike `/ips`, this endpoint does not enumerate the address
    space, so it stays cheap on `/16`s and larger."""
    subnet, util = await service.compute_utilization(db, subnet_id)
    return SubnetUtilization(subnet_id=subnet.id, cidr=str(subnet.cidr), **util)
