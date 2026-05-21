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


def usable_hosts(cidr: str) -> int:
    """Number of host-usable addresses in `cidr`.

    Excludes network + broadcast on /≤30 (the same accounting as
    `compute_utilization`), and keeps both addresses on /31 (RFC 3021)
    and /32 (loopback) so the fill bar shows 100% for those rather than
    dividing by zero.
    """
    net = IPv4Network(cidr, strict=False)
    return net.num_addresses if net.prefixlen >= 31 else max(0, net.num_addresses - 2)


async def list_subnets(
    db: AsyncSession,
    page: PageParams,
    site_id: int | None = None,
    vlan_id: int | None = None,
    vrf_id: int | None = None,
) -> tuple[list[Subnet], int, dict[int, int]]:
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
    items = list(result.scalars().all())

    # Per-page IP counts in one grouped SELECT — the list endpoint now
    # carries `used` so the UI can render a fill bar without hitting the
    # utilisation endpoint N times. Skipped when the page is empty so the
    # IN-clause never receives an empty tuple.
    #
    # Counts use the SAME accounting as `compute_utilization`: boundary
    # IPs (network / broadcast) on /≤30 are excluded. Without this, an
    # operator who recorded e.g. .0 or .255 would see `used > usable` on
    # the list bar — disagreeing with the per-subnet utilisation page
    # and making capacity triage misleading. Codex P2 on #74.
    ip_counts: dict[int, int] = {}
    if items:
        ids = [s.id for s in items]
        boundary_pairs: set[tuple[int, str]] = set()
        for s in items:
            net = IPv4Network(str(s.cidr), strict=False)
            if net.prefixlen < 31:
                boundary_pairs.add((s.id, str(net.network_address)))
                boundary_pairs.add((s.id, str(net.broadcast_address)))

        rows = (
            await db.execute(
                select(Ip.subnet_id, Ip.address)
                .where(Ip.subnet_id.in_(ids))
            )
        ).all()
        for sid, addr in rows:
            if (int(sid), str(addr)) in boundary_pairs:
                continue
            ip_counts[int(sid)] = ip_counts.get(int(sid), 0) + 1

    return items, int(total), ip_counts


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
    # Block a VRF move that would strand existing children in a different
    # scope. Without this guard the children silently violate the "same
    # VRF as parent" invariant and any later edit to them fails with a
    # confusing INVALID_PARENT (Codex P1 on #64).
    if "vrf_id" in patch and new_vrf != subnet.vrf_id:
        await _reject_vrf_move_with_children(db, subnet, new_vrf)
    for field, value in patch.items():
        setattr(subnet, field, value)
    with catch_integrity_errors():
        await db.commit()
    await db.refresh(subnet)
    return subnet


async def _reject_vrf_move_with_children(
    db: AsyncSession, subnet: Subnet, new_vrf: int | None
) -> None:
    """Refuse to move a subnet to a new VRF while children point to it.

    Operators should either re-parent the children first, or move the whole
    subtree atomically via separate calls. Surfacing this as a 400 is much
    safer than silently leaving the hierarchy inconsistent.
    """
    result = await db.execute(
        select(Subnet.id, Subnet.cidr).where(Subnet.parent_subnet_id == subnet.id)
    )
    children = list(result.all())
    if not children:
        return
    business_rule(
        "INVALID_PARENT",
        f"Cannot move subnet {subnet.cidr} to a different VRF while {len(children)} "
        f"child subnet(s) still reference it. Detach or move the children first.",
        details={
            "subnet_id": subnet.id,
            "current_vrf_id": subnet.vrf_id,
            "requested_vrf_id": new_vrf,
            "child_ids": [int(c.id) for c in children],
        },
    )


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


def _dhcp_bounds(subnet: Subnet) -> tuple[IPv4Address, IPv4Address] | None:
    """Return the configured DHCP pool as `(start, end)` IPv4Address objects.

    Returns `None` when DHCP is disabled or either bound is missing, so
    callers can fall back to "no DHCP range" with a single truthy check.
    """
    if not (subnet.dhcp_enabled and subnet.dhcp_range_start and subnet.dhcp_range_end):
        return None
    return IPv4Address(subnet.dhcp_range_start), IPv4Address(subnet.dhcp_range_end)


async def next_free_ip(db: AsyncSession, subnet_id: int) -> str:
    subnet = await get_subnet(db, subnet_id)
    network = IPv4Network(subnet.cidr, strict=False)
    _check_size(network)

    used = await _used_addresses(db, subnet_id)
    skip: set[str] = {str(IPv4Address(subnet.gateway))} if subnet.gateway else set()

    # Skip addresses inside the DHCP pool: they're reserved for dynamic
    # leases, so handing one back to the "next free for manual assignment"
    # flow would silently steal a DHCP address from clients.
    dhcp = _dhcp_bounds(subnet)

    for host in network.hosts():
        s = str(host)
        if s in used or s in skip:
            continue
        if dhcp is not None and dhcp[0] <= host <= dhcp[1]:
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


def _auto_group_roots(roots: list[dict], supernet_prefix: int) -> list[dict]:
    """Wrap flat root subnets under synthetic supernet parents so the tree
    view shows meaningful hierarchy even when no `parent_subnet_id` is
    set anywhere. Roots that are already shorter than `supernet_prefix`
    pass through as-is; singletons stay at the root level (no point in
    wrapping a single child).

    Synthetic nodes carry `synthetic=True` and a negative id derived from
    the supernet CIDR so the frontend can render them differently and
    refuse navigation (there's no DB row to open).
    """
    if not roots or supernet_prefix <= 0 or supernet_prefix >= 32:
        return roots

    buckets: dict[str, list[dict]] = {}
    passthrough: list[dict] = []
    for r in roots:
        net = IPv4Network(r["cidr"], strict=False)
        # Already a supernet at or above the grouping prefix — nothing to
        # fold it under.
        if net.prefixlen <= supernet_prefix:
            passthrough.append(r)
            continue
        super_cidr = str(net.supernet(new_prefix=supernet_prefix))
        buckets.setdefault(super_cidr, []).append(r)

    grouped: list[dict] = list(passthrough)
    for super_cidr, members in buckets.items():
        if len(members) <= 1:
            grouped.extend(members)
            continue
        members.sort(key=lambda m: m["cidr"])
        super_net = IPv4Network(super_cidr, strict=False)
        super_usable = (
            super_net.num_addresses
            if super_net.prefixlen >= 31
            else max(0, super_net.num_addresses - 2)
        )
        grouped.append(
            {
                # Negative id keeps these out of any URL-based lookup —
                # the frontend treats them as not-navigable.
                "id": -(abs(hash(("autogroup", super_cidr))) % 100_000_000) - 1,
                "cidr": super_cidr,
                "site_id": members[0]["site_id"],
                "vrf_id": members[0]["vrf_id"],
                "vlan_id": None,
                "parent_subnet_id": None,
                "description": None,
                "gateway": None,
                "usable": super_usable,
                "used": sum(m["used"] for m in members),
                "synthetic": True,
                "children": members,
            }
        )
    grouped.sort(key=lambda x: x["cidr"])
    return grouped


async def build_subnet_tree(
    db: AsyncSession,
    vrf_id: int | None,
    auto_group_prefix: int | None = 16,
) -> list[dict]:
    """Return the subnet hierarchy as a list of root nodes.

    `vrf_id` filters the scope: `None` returns the global VRF tree,
    a specific id returns that VRF's tree. We always fetch every subnet
    in scope in one query and assemble in Python — Postgres recursive
    CTEs are overkill for a tree that's at most a few hundred nodes.

    `auto_group_prefix` (default 16) wraps groups of root subnets that
    share a common /N supernet under a synthetic virtual parent, so the
    tree view shows real hierarchy even on flat deployments that don't
    use `parent_subnet_id`. Pass `None` (or 0) to disable and get a true
    flat-root list.

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

    # Per-subnet IP counts so each tree row can show a fill bar without
    # extra round-trips. Same boundary-aware accounting as the list view
    # and `compute_utilization`: network/broadcast addresses on /≤30
    # don't count toward `used`, so the bar can't read > 100%. DHCP-range
    # slots without a DB row stay invisible (consistent with how
    # `compute_utilization` aggregates).
    ip_counts: dict[int, int] = {}
    if by_id:
        boundary_pairs: set[tuple[int, str]] = set()
        for sid, s in by_id.items():
            net = IPv4Network(str(s.cidr), strict=False)
            if net.prefixlen < 31:
                boundary_pairs.add((sid, str(net.network_address)))
                boundary_pairs.add((sid, str(net.broadcast_address)))
        rows = (
            await db.execute(
                select(Ip.subnet_id, Ip.address).where(Ip.subnet_id.in_(by_id.keys()))
            )
        ).all()
        for sid, addr in rows:
            if (int(sid), str(addr)) in boundary_pairs:
                continue
            ip_counts[int(sid)] = ip_counts.get(int(sid), 0) + 1

    def node_for(s: Subnet) -> dict:
        return {
            "id": s.id,
            "cidr": str(s.cidr),
            "site_id": s.site_id,
            "vrf_id": s.vrf_id,
            "vlan_id": s.vlan_id,
            "parent_subnet_id": s.parent_subnet_id,
            "description": s.description,
            "gateway": None if s.gateway is None else str(s.gateway),
            "usable": usable_hosts(str(s.cidr)),
            "used": int(ip_counts.get(s.id, 0)),
            "children": [node_for(c) for c in children_of.get(s.id, [])],
        }

    roots = [node_for(s) for s in children_of.get(None, [])]
    if auto_group_prefix and auto_group_prefix > 0:
        roots = _auto_group_roots(roots, supernet_prefix=auto_group_prefix)
    return roots


async def list_subnet_ips(
    db: AsyncSession, subnet_id: int
) -> tuple[Subnet, list[SubnetIpEntry]]:
    subnet = await get_subnet(db, subnet_id)
    network = IPv4Network(subnet.cidr, strict=False)
    _check_size(network)

    used = await _used_addresses(db, subnet_id)
    # Pre-compute the DHCP pool bounds once so we don't reparse the strings
    # for every host in the loop.
    dhcp = _dhcp_bounds(subnet)

    entries: list[SubnetIpEntry] = []
    for host in network.hosts():
        s = str(host)
        ip = used.get(s)
        if ip is None:
            # No row in the DB. If the host falls inside the configured
            # DHCP pool, surface it as "dhcp" in the grid so the operator
            # can see at a glance which range is dedicated to leases.
            # Manual assignment from this slot is still possible — the
            # editor uses the `prefilled-address` flow, not next-free.
            if dhcp is not None and dhcp[0] <= host <= dhcp[1]:
                entries.append(SubnetIpEntry(address=s, status="dhcp"))
            else:
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
