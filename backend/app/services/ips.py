"""IPs service.

Pre-validates that `address ∈ subnet.cidr` in Python before insert. The DB
trigger `ips_check_in_subnet` is kept as the safety net — anything that
bypasses the service (manual SQL) will still be rejected.
"""

from __future__ import annotations

from ipaddress import IPv4Address, IPv4Network

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ip import Ip
from app.models.subnet import Subnet
from app.schemas.common import PageParams
from app.schemas.ip import (
    BulkIpAction,
    BulkIpRange,
    IpCreate,
    IpStatus,
    IpUpdate,
)
from app.services.errors import business_rule, catch_integrity_errors, not_found

# Cap on a single bulk-IP call. Picked to comfortably cover a full /24
# (254 host addresses) plus a bit of slack for /23 sweeps. Larger ranges
# should be split client-side — keeps each transaction small enough to
# stay inside the request timeout and the audit log readable.
_MAX_BULK_RANGE = 512


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


# --- Bulk range operations -------------------------------------------------


async def bulk_ip_range(
    db: AsyncSession, subnet_id: int, payload: BulkIpRange
) -> dict[str, int]:
    """Reserve or release every address in `[start, end]` within one subnet.

    All-or-nothing transaction: any FK / trigger violation rolls back the
    whole batch. The cap (`_MAX_BULK_RANGE`) and the in-subnet check up
    front mean by the time we reach the loop we know every address is
    valid — the loop just chooses between INSERT / UPDATE / DELETE / skip
    per existing-row state.

    Boundary addresses (network / broadcast on /≤30) are left untouched;
    the GiST exclusion would still accept them but counting them as
    "reserved" would break the same accounting `_per_subnet_used_counts`
    relies on (Codex P2 thread on #74).
    """
    subnet = await db.get(Subnet, subnet_id)
    if subnet is None:
        not_found("Subnet", subnet_id)

    network = IPv4Network(str(subnet.cidr), strict=False)
    start_addr = IPv4Address(payload.start)
    end_addr = IPv4Address(payload.end)
    if start_addr > end_addr:
        business_rule(
            "INVALID_RANGE",
            f"Range start ({start_addr}) is after end ({end_addr}).",
            details={"start": str(start_addr), "end": str(end_addr)},
        )
    if start_addr not in network or end_addr not in network:
        business_rule(
            "IP_NOT_IN_SUBNET",
            f"Range {start_addr}–{end_addr} is not fully contained in {network}.",
            details={
                "start": str(start_addr),
                "end": str(end_addr),
                "cidr": str(network),
                "subnet_id": subnet_id,
            },
        )
    span = int(end_addr) - int(start_addr) + 1
    if span > _MAX_BULK_RANGE:
        business_rule(
            "BULK_RANGE_TOO_LARGE",
            f"Bulk range {start_addr}–{end_addr} covers {span} addresses; "
            f"the per-call cap is {_MAX_BULK_RANGE}. Split the range and "
            f"retry.",
            details={"requested": span, "max": _MAX_BULK_RANGE},
        )

    # Boundary set so we never touch the network/broadcast slots.
    boundaries: set[str] = set()
    if network.prefixlen < 31:
        boundaries.add(str(network.network_address))
        boundaries.add(str(network.broadcast_address))

    targets = [
        str(IPv4Address(int(start_addr) + i))
        for i in range(span)
        if str(IPv4Address(int(start_addr) + i)) not in boundaries
    ]

    # One round-trip to find existing rows in the range so the inner loop
    # is a pure dispatch — no per-address SELECT.
    existing_rows = (
        await db.execute(
            select(Ip).where(
                Ip.subnet_id == subnet_id,
                cast(Ip.address, String).in_(targets),
            )
        )
    ).scalars().all()
    existing_by_addr: dict[str, Ip] = {str(r.address): r for r in existing_rows}

    created = updated = deleted = skipped = 0
    if payload.action is BulkIpAction.release:
        for addr in targets:
            row = existing_by_addr.get(addr)
            if row is None:
                skipped += 1
                continue
            await db.delete(row)
            deleted += 1
    else:  # reserve
        for addr in targets:
            row = existing_by_addr.get(addr)
            if row is None:
                db.add(
                    Ip(
                        subnet_id=subnet_id,
                        address=addr,
                        status=payload.status,
                        description=payload.description,
                    )
                )
                created += 1
            elif payload.overwrite:
                row.status = payload.status
                if payload.description is not None:
                    row.description = payload.description
                updated += 1
            else:
                skipped += 1

    with catch_integrity_errors():
        await db.commit()

    return {
        "requested": span,
        "created": created,
        "updated": updated,
        "deleted": deleted,
        "skipped": skipped + (span - len(targets)),
    }
