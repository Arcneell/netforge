"""Subnets service — relies on the GiST exclusion constraint for overlap.

Also hosts the utility endpoints declared in phase 4:

- `next_free_ip(subnet_id)` — first unused host address in the subnet.
- `list_subnet_ips(subnet_id)` — every host address with its status
  (assigned/reserved/dhcp or synthetic `"free"` for the unused ones).

Both refuse to operate on networks larger than `_MAX_HOSTS_FOR_SCAN` host
addresses to keep response sizes and Python set memory bounded.
"""

from __future__ import annotations

from ipaddress import IPv4Address, IPv4Network

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ip import Ip
from app.models.subnet import Subnet
from app.schemas.common import PageParams
from app.schemas.subnet import SubnetCreate, SubnetIpEntry, SubnetUpdate
from app.services.errors import business_rule, catch_integrity_errors, not_found

# Hard cap on /N scans: 4096 host addresses (i.e. /20). Anything larger is a
# planning error in a documentation tool — surface a 400 rather than try to
# materialise 65k entries.
_MAX_HOSTS_FOR_SCAN = 4096


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


# --- Utility queries (phase 4) ----------------------------------------------


def _check_size(network: IPv4Network) -> None:
    # network.hosts() excludes network/broadcast; .num_addresses includes them.
    if network.num_addresses > _MAX_HOSTS_FOR_SCAN:
        business_rule(
            "SUBNET_TOO_LARGE",
            f"Operation refused: subnet has more than {_MAX_HOSTS_FOR_SCAN} addresses.",
            details={"cidr": str(network), "max": _MAX_HOSTS_FOR_SCAN},
        )


async def _used_addresses(db: AsyncSession, subnet_id: int) -> dict[str, Ip]:
    result = await db.execute(select(Ip).where(Ip.subnet_id == subnet_id))
    return {str(ip.address): ip for ip in result.scalars().all()}


async def next_free_ip(db: AsyncSession, subnet_id: int) -> str:
    subnet = await get_subnet(db, subnet_id)
    network = IPv4Network(subnet.cidr, strict=False)
    _check_size(network)

    used = await _used_addresses(db, subnet_id)
    skip: set[str] = {str(IPv4Address(subnet.gateway))} if subnet.gateway else set()

    for host in network.hosts():
        s = str(host)
        if s in used or s in skip:
            continue
        return s

    business_rule(
        "SUBNET_FULL",
        "No free IP available in this subnet.",
        details={"cidr": str(network)},
    )


async def list_subnet_ips(
    db: AsyncSession, subnet_id: int
) -> tuple[Subnet, list[SubnetIpEntry]]:
    subnet = await get_subnet(db, subnet_id)
    network = IPv4Network(subnet.cidr, strict=False)
    _check_size(network)

    used = await _used_addresses(db, subnet_id)

    entries: list[SubnetIpEntry] = []
    for host in network.hosts():
        s = str(host)
        ip = used.get(s)
        if ip is None:
            entries.append(SubnetIpEntry(address=s, status="free"))
        else:
            entries.append(
                SubnetIpEntry(
                    address=s,
                    status=ip.status.value
                    if hasattr(ip.status, "value")
                    else str(ip.status),
                    hostname=ip.hostname,
                    mac=None if ip.mac is None else str(ip.mac),
                    device_id=ip.device_id,
                    description=ip.description,
                )
            )
    return subnet, entries
