"""Subnets service — relies on the GiST exclusion constraint for overlap."""

from __future__ import annotations

from ipaddress import IPv4Address, IPv4Network

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subnet import Subnet
from app.schemas.common import PageParams
from app.schemas.subnet import SubnetCreate, SubnetUpdate
from app.services.errors import business_rule, catch_integrity_errors, not_found


async def list_subnets(
    db: AsyncSession,
    page: PageParams,
    site_id: int | None = None,
    vlan_id: int | None = None,
) -> tuple[list[Subnet], int]:
    base = select(Subnet)
    count_q = select(func.count()).select_from(Subnet)
    if site_id is not None:
        base = base.where(Subnet.site_id == site_id)
        count_q = count_q.where(Subnet.site_id == site_id)
    if vlan_id is not None:
        base = base.where(Subnet.vlan_id == vlan_id)
        count_q = count_q.where(Subnet.vlan_id == vlan_id)

    total = (await db.execute(count_q)).scalar() or 0
    result = await db.execute(
        base.order_by(Subnet.id).offset(page.offset).limit(page.limit)
    )
    return list(result.scalars().all()), int(total)


async def get_subnet(db: AsyncSession, subnet_id: int) -> Subnet:
    subnet = await db.get(Subnet, subnet_id)
    if subnet is None:
        not_found("Subnet", subnet_id)
    return subnet


def _validate_dhcp_range(cidr: str, payload: dict) -> None:
    """Reject DHCP ranges that fall outside the CIDR (DB has no such trigger)."""
    network = IPv4Network(cidr, strict=False)
    for key in ("gateway", "dhcp_range_start", "dhcp_range_end"):
        addr = payload.get(key)
        if addr is None:
            continue
        if IPv4Address(addr) not in network:
            business_rule(
                "ADDRESS_OUT_OF_SUBNET",
                f"{key} ({addr}) is not contained in {cidr}.",
                details={"field": key, "address": addr, "cidr": cidr},
            )


async def create_subnet(db: AsyncSession, payload: SubnetCreate) -> Subnet:
    data = payload.model_dump()
    _validate_dhcp_range(data["cidr"], data)
    subnet = Subnet(**data)
    db.add(subnet)
    with catch_integrity_errors():
        # GiST exclusion → 409 SUBNET_OVERLAP via errors.catch_integrity_errors.
        await db.commit()
    await db.refresh(subnet)
    return subnet


async def update_subnet(
    db: AsyncSession, subnet_id: int, payload: SubnetUpdate
) -> Subnet:
    subnet = await get_subnet(db, subnet_id)
    patch = payload.model_dump(exclude_unset=True)
    cidr = patch.get("cidr", subnet.cidr)
    merged = {
        "gateway": patch.get("gateway", subnet.gateway),
        "dhcp_range_start": patch.get("dhcp_range_start", subnet.dhcp_range_start),
        "dhcp_range_end": patch.get("dhcp_range_end", subnet.dhcp_range_end),
    }
    _validate_dhcp_range(cidr, merged)
    for field, value in patch.items():
        setattr(subnet, field, value)
    with catch_integrity_errors():
        await db.commit()
    await db.refresh(subnet)
    return subnet


async def delete_subnet(db: AsyncSession, subnet_id: int) -> None:
    subnet = await get_subnet(db, subnet_id)
    # ips cascades automatically (ON DELETE CASCADE).
    await db.delete(subnet)
    with catch_integrity_errors():
        await db.commit()
