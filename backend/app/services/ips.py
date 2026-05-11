"""IPs service.

Pre-validates that `address ∈ subnet.cidr` in Python before insert. The DB
trigger `ips_check_in_subnet` is kept as the safety net — anything that
bypasses the service (manual SQL) will still be rejected.
"""

from __future__ import annotations

from ipaddress import IPv4Address, IPv4Network

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ip import Ip
from app.models.subnet import Subnet
from app.schemas.common import PageParams
from app.schemas.ip import IpCreate, IpStatus, IpUpdate
from app.services.errors import business_rule, catch_integrity_errors, not_found


async def list_ips(
    db: AsyncSession,
    page: PageParams,
    subnet_id: int | None = None,
    status: IpStatus | None = None,
    q: str | None = None,
) -> tuple[list[Ip], int]:
    base = select(Ip)
    count_q = select(func.count()).select_from(Ip)
    if subnet_id is not None:
        base = base.where(Ip.subnet_id == subnet_id)
        count_q = count_q.where(Ip.subnet_id == subnet_id)
    if status is not None:
        base = base.where(Ip.status == status)
        count_q = count_q.where(Ip.status == status)
    if q:
        like = f"%{q}%"
        cond = or_(Ip.hostname.ilike(like), func.text(Ip.address).ilike(like))
        base = base.where(cond)
        count_q = count_q.where(cond)

    total = (await db.execute(count_q)).scalar() or 0
    result = await db.execute(
        base.order_by(Ip.address).offset(page.offset).limit(page.limit)
    )
    return list(result.scalars().all()), int(total)


async def get_ip(db: AsyncSession, ip_id: int) -> Ip:
    ip = await db.get(Ip, ip_id)
    if ip is None:
        not_found("IP", ip_id)
    return ip


async def _check_address_in_subnet(
    db: AsyncSession, subnet_id: int, address: str
) -> None:
    """Reject early if `address` is not contained in the referenced subnet."""
    subnet = await db.get(Subnet, subnet_id)
    if subnet is None:
        not_found("Subnet", subnet_id)
    # asyncpg deserialises CIDR columns to ipaddress.IPv4Network, which is
    # not JSON-serialisable — coerce to str for the error response details.
    cidr_str = str(subnet.cidr)
    network = IPv4Network(cidr_str, strict=False)
    if IPv4Address(address) not in network:
        business_rule(
            "IP_NOT_IN_SUBNET",
            f"{address} is not contained in {cidr_str}.",
            details={"address": address, "cidr": cidr_str, "subnet_id": subnet_id},
        )


async def create_ip(db: AsyncSession, payload: IpCreate) -> Ip:
    data = payload.model_dump()
    await _check_address_in_subnet(db, data["subnet_id"], data["address"])
    ip = Ip(**data)
    db.add(ip)
    with catch_integrity_errors():
        await db.commit()
    await db.refresh(ip)
    return ip


async def update_ip(db: AsyncSession, ip_id: int, payload: IpUpdate) -> Ip:
    ip = await get_ip(db, ip_id)
    patch = payload.model_dump(exclude_unset=True)

    # If subnet_id or address change, re-validate inclusion.
    new_subnet_id = patch.get("subnet_id", ip.subnet_id)
    new_address = patch.get("address", ip.address)
    if "subnet_id" in patch or "address" in patch:
        await _check_address_in_subnet(db, new_subnet_id, new_address)

    for field, value in patch.items():
        setattr(ip, field, value)
    with catch_integrity_errors():
        await db.commit()
    await db.refresh(ip)
    return ip


async def delete_ip(db: AsyncSession, ip_id: int) -> None:
    ip = await get_ip(db, ip_id)
    await db.delete(ip)
    with catch_integrity_errors():
        await db.commit()
