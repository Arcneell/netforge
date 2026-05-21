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
    vrf_id: int | None = None,
) -> tuple[list[Subnet], int]:
    base = select(Subnet)
    count_q = select(func.count()).select_from(Subnet)
    if site_id is not None:
        base = base.where(Subnet.site_id == site_id)
        count_q = count_q.where(Subnet.site_id == site_id)
    if vlan_id is not None:
        base = base.where(Subnet.vlan_id == vlan_id)
        count_q = count_q.where(Subnet.vlan_id == vlan_id)
    if vrf_id is not None:
        # Special value 0 means "global scope" (vrf_id IS NULL) — the
        # router translates the explicit `?vrf_id=0` so admins can browse
        # only the unscoped subnets.
        if vrf_id == 0:
            base = base.where(Subnet.vrf_id.is_(None))
            count_q = count_q.where(Subnet.vrf_id.is_(None))
        else:
            base = base.where(Subnet.vrf_id == vrf_id)
            count_q = count_q.where(Subnet.vrf_id == vrf_id)

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


async def _validate_parent(
    db: AsyncSession,
    *,
    cidr: str,
    vrf_id: int | None,
    parent_subnet_id: int | None,
    self_id: int | None = None,
) -> None:
    """Three checks when a parent is set:
      1. The parent exists.
      2. It lives in the same VRF (mixing routing scopes makes no sense).
      3. The child CIDR is strictly contained in the parent CIDR.
    Plus a structural guard: a subnet cannot be its own parent.
    """
    if parent_subnet_id is None:
        return
    if self_id is not None and self_id == parent_subnet_id:
        business_rule(
            "INVALID_PARENT",
            "A subnet cannot be its own parent.",
            details={"subnet_id": self_id},
        )
    parent = await db.get(Subnet, parent_subnet_id)
    if parent is None:
        business_rule(
            "INVALID_PARENT",
            f"Parent subnet {parent_subnet_id} does not exist.",
            details={"parent_subnet_id": parent_subnet_id},
        )
    if parent.vrf_id != vrf_id:
        business_rule(
            "INVALID_PARENT",
            "Parent and child subnet must live in the same VRF.",
            details={
                "parent_vrf_id": parent.vrf_id,
                "child_vrf_id": vrf_id,
            },
        )
    child_net = IPv4Network(cidr, strict=False)
    parent_net = IPv4Network(str(parent.cidr), strict=False)
    if not (child_net.subnet_of(parent_net) and child_net != parent_net):
        business_rule(
            "INVALID_PARENT",
            f"{cidr} is not strictly contained in parent {parent_net}.",
            details={"child_cidr": str(child_net), "parent_cidr": str(parent_net)},
        )


async def create_subnet(db: AsyncSession, payload: SubnetCreate) -> Subnet:
    data = payload.model_dump()
    _validate_dhcp_range(data["cidr"], data)
    await _validate_parent(
        db,
        cidr=data["cidr"],
        vrf_id=data.get("vrf_id"),
        parent_subnet_id=data.get("parent_subnet_id"),
    )
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
    # If parent/vrf change, re-run containment + same-VRF checks against
    # the new effective values.
    new_vrf = patch.get("vrf_id", subnet.vrf_id)
    new_parent = patch.get("parent_subnet_id", subnet.parent_subnet_id)
    await _validate_parent(
        db,
        cidr=str(cidr),
        vrf_id=new_vrf,
        parent_subnet_id=new_parent,
        self_id=subnet.id,
    )
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


async def compute_utilization(
    db: AsyncSession, subnet_id: int
) -> tuple[Subnet, dict[str, int]]:
    """Snapshot of how full a subnet is — usable space, count per IP status.

    Does NOT scan the address space (unlike `list_subnet_ips`), so it works
    on subnets larger than `_MAX_HOSTS_FOR_SCAN`. Just two SELECTs: one to
    fetch the subnet row, one aggregated count grouped by status.

    Counts are restricted to *host-usable* addresses so the numbers align
    with the `/ips` view: on prefixes shorter than /31 we exclude rows
    that happen to land on the network or broadcast address (nothing
    prevents an operator from creating an `Ip` row at the boundary today
    — see GiST overlap exclusion which only checks overlap, not bounds).
    /31 and /32 keep every address per RFC 3021 / loopback. Without this
    filter `used_pct` could exceed 100 when boundary addresses were
    present, which Codex flagged on PR #59.
    """
    subnet = await get_subnet(db, subnet_id)
    network = IPv4Network(subnet.cidr, strict=False)
    usable = (
        network.num_addresses if network.prefixlen >= 31 else network.num_addresses - 2
    )

    base = select(Ip.status, func.count(Ip.id)).where(Ip.subnet_id == subnet_id)
    if network.prefixlen < 31:
        # Exclude the network + broadcast addresses from the count so the
        # ratio matches `usable`. We compare on the canonical string form
        # because `Ip.address` is INET and asyncpg round-trips strings.
        base = base.where(
            Ip.address != str(network.network_address),
            Ip.address != str(network.broadcast_address),
        )

    counts_rows = (await db.execute(base.group_by(Ip.status))).all()
    by_status: dict[str, int] = {"assigned": 0, "reserved": 0, "dhcp": 0}
    for status_val, count in counts_rows:
        key = status_val.value if hasattr(status_val, "value") else str(status_val)
        by_status[key] = int(count)

    consumed = sum(by_status.values())
    return subnet, {
        "usable": usable,
        "free": max(0, usable - consumed),
        "used_pct": (consumed * 100 // usable) if usable > 0 else 0,
        **{f"status_{k}": v for k, v in by_status.items()},
    }


async def build_subnet_tree(
    db: AsyncSession, vrf_id: int | None
) -> list[dict]:
    """Return the subnet hierarchy as a list of root nodes.

    `vrf_id` filters the scope: `None` returns the global VRF tree,
    a specific id returns that VRF's tree. We always fetch every subnet
    in scope in one query and assemble in Python — Postgres recursive
    CTEs are overkill for a tree that's at most a few hundred nodes.

    A "root" is a subnet whose `parent_subnet_id` is either NULL or
    points outside the current scope (e.g. a deleted parent that hasn't
    been cleaned up). Sibling order is ascending by CIDR.
    """
    base = select(Subnet)
    base = (
        base.where(Subnet.vrf_id.is_(None))
        if vrf_id is None
        else base.where(Subnet.vrf_id == vrf_id)
    )
    result = await db.execute(base)
    rows: list[Subnet] = list(result.scalars().all())

    by_id: dict[int, Subnet] = {s.id: s for s in rows}
    children_of: dict[int | None, list[Subnet]] = {}
    for s in rows:
        # If the parent isn't in scope, treat it as a root for this view.
        parent_key = (
            s.parent_subnet_id
            if s.parent_subnet_id in by_id
            else None
        )
        children_of.setdefault(parent_key, []).append(s)

    # Sort siblings by CIDR (lexicographic on canonical form is fine for
    # IPv4 — Postgres CIDR stores in canonical form anyway).
    for siblings in children_of.values():
        siblings.sort(key=lambda s: str(s.cidr))

    def node_for(s: Subnet) -> dict:
        return {
            "id": s.id,
            "cidr": str(s.cidr),
            "site_id": s.site_id,
            "vrf_id": s.vrf_id,
            "parent_subnet_id": s.parent_subnet_id,
            "description": s.description,
            "children": [node_for(c) for c in children_of.get(s.id, [])],
        }

    return [node_for(s) for s in children_of.get(None, [])]


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
