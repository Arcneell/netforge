"""Reference resolution — the import's read side.

Every CSV row points at entities by their human-readable key (`site_code`,
`vlan_id`, `switch_name`, ...). Resolving those keys used to mean one SELECT
per row per column, which made a 10 MiB upload issue hundreds of thousands of
round-trips and — worse — made `_find_subnet_for` re-read the *entire*
`subnets` table for every single IP row (O(rows × subnets)).

This module centralises those reads behind `_RefCache`:

  - **Memoised by key.** A lookup is issued at most once per distinct key for
    the whole import, misses included (negative caching). The query shape is
    unchanged — still `SELECT ... WHERE <natural key> = :k` — so the number of
    statements now scales with the number of *distinct references* in the
    file, not with the number of rows.
  - **Write-through.** The persist layer registers every entity it creates
    (`remember_*`), so a CSV that creates a site and then a room pointing at
    it still resolves — the cache never goes stale behind an insert the import
    itself performed.
  - **Containment index.** Subnets get a dedicated structure (`_SubnetIndex`)
    so "which subnet contains this address" costs one table read per import
    instead of one per row.

The cache lives in a `ContextVar` rather than in the persist signatures: the
`_persist_*` functions keep their `(db, row)` shape, which keeps them directly
callable (and unit-testable) outside a driver run. When no scope is active,
`_refs()` hands out a throwaway cache, so an isolated call emits exactly the
same statements it always did.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from ipaddress import IPv4Address, IPv4Network

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import Room, Site
from app.models.device import Device
from app.models.ip import Ip
from app.models.link import Link
from app.models.port import Port
from app.models.subnet import Subnet
from app.models.switch import Switch
from app.models.vlan import Vlan
from app.services.csv_import.errors import _RefError

_IPV4_ALL_ONES = 0xFFFFFFFF


class _SubnetIndex:
    """Longest-prefix-agnostic containment index over a snapshot of `subnets`.

    Built once per import from a single `SELECT * FROM subnets`. Replaces the
    previous linear rescan, which reloaded and re-parsed every subnet row for
    every IP row of the CSV.

    **Why an index by prefix length** rather than a sorted array + bisect or a
    radix/patricia trie: an IPv4 CIDR only has 33 possible prefix lengths, and
    a real inventory uses a handful of them. Bucketing on `prefixlen` and
    masking the query address turns the search into at most 33 dict probes —
    constant with respect to the number of subnets — while staying a dozen
    lines of plain Python. A trie would also be O(32) but needs far more code
    to maintain, and bisect on a sorted array would need extra bookkeeping to
    reproduce the tie-breaking rule below.

    **Semantics are exactly those of the old linear scan**, deliberately:

      - *No VRF filtering.* The old loop walked every row regardless of
        `vrf_id`, so two subnets sharing a CIDR in different VRFs resolve to
        whichever one the DB returned first. We keep each row's position in
        the result set and break ties on it, reproducing that.
      - *Nested subnets are NOT resolved most-specific-first.* The old loop
        returned the first containing row in DB order, so a /16 listed before
        its /24 wins. Same tie-break, same winner. (Changing this to
        longest-prefix-match would be a behaviour change and is out of scope.)
      - *No match* returns `None`; the caller raises the same `_RefError`.
    """

    __slots__ = ("_by_prefixlen", "_prefixlens")

    def __init__(self, subnets: Sequence[Subnet]) -> None:
        # prefixlen → {masked network address as int: (row position, subnet)}
        by_prefixlen: dict[int, dict[int, tuple[int, Subnet]]] = {}
        for position, subnet in enumerate(subnets):
            net = IPv4Network(subnet.cidr, strict=False)
            bucket = by_prefixlen.setdefault(net.prefixlen, {})
            key = int(net.network_address)
            previous = bucket.get(key)
            # Duplicate CIDRs are possible across VRFs — keep the row the old
            # scan would have hit first.
            if previous is None or position < previous[0]:
                bucket[key] = (position, subnet)
        self._by_prefixlen = by_prefixlen
        self._prefixlens = sorted(by_prefixlen)

    def find(self, address: IPv4Address) -> Subnet | None:
        addr = int(address)
        best: tuple[int, Subnet] | None = None
        for prefixlen in self._prefixlens:
            mask = (_IPV4_ALL_ONES << (32 - prefixlen)) & _IPV4_ALL_ONES
            hit = self._by_prefixlen[prefixlen].get(addr & mask)
            if hit is not None and (best is None or hit[0] < best[0]):
                best = hit
        return None if best is None else best[1]


class _RefCache:
    """Per-import memo of every reference lookup, plus the subnet index.

    Scoped to one `run_import` / `run_bulk_import` call, i.e. to one
    transaction. Nothing in here survives the commit or the rollback, so a
    cached row can never be read back in a later request.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._sites: dict[str, Site | None] = {}
        self._rooms: dict[tuple[int, str], Room | None] = {}
        self._vlans: dict[int, Vlan | None] = {}
        self._devices: dict[str, Device | None] = {}
        self._switches: dict[str, Switch | None] = {}
        self._ports: dict[tuple[int, int], Port | None] = {}
        self._ips: dict[str, Ip | None] = {}
        self._subnets_by_cidr: dict[str, Subnet | None] = {}
        self._links: dict[tuple[int, int], Link | None] = {}
        self._subnet_index: _SubnetIndex | None = None

    # -- reads -------------------------------------------------------------

    async def site_by_code(self, code: str) -> Site | None:
        if code not in self._sites:
            self._sites[code] = (
                await self.db.execute(select(Site).where(Site.code == code))
            ).scalar_one_or_none()
        return self._sites[code]

    async def room_by_code(self, site_id: int, code: str) -> Room | None:
        key = (site_id, code)
        if key not in self._rooms:
            self._rooms[key] = (
                await self.db.execute(
                    select(Room).where(Room.site_id == site_id, Room.code == code)
                )
            ).scalar_one_or_none()
        return self._rooms[key]

    async def vlan_by_public_id(self, vlan_id: int) -> Vlan | None:
        if vlan_id not in self._vlans:
            self._vlans[vlan_id] = (
                await self.db.execute(select(Vlan).where(Vlan.vlan_id == vlan_id))
            ).scalar_one_or_none()
        return self._vlans[vlan_id]

    async def device_by_name(self, name: str) -> Device | None:
        if name not in self._devices:
            self._devices[name] = (
                await self.db.execute(select(Device).where(Device.name == name))
            ).scalar_one_or_none()
        return self._devices[name]

    async def switch_by_name(self, name: str) -> Switch | None:
        if name not in self._switches:
            self._switches[name] = (
                await self.db.execute(select(Switch).where(Switch.name == name))
            ).scalar_one_or_none()
        return self._switches[name]

    async def port_on_switch(self, switch_id: int, number: int) -> Port | None:
        key = (switch_id, number)
        if key not in self._ports:
            self._ports[key] = (
                await self.db.execute(
                    select(Port).where(
                        Port.switch_id == switch_id, Port.number == number
                    )
                )
            ).scalar_one_or_none()
        return self._ports[key]

    async def ip_by_address(self, address: str) -> Ip | None:
        if address not in self._ips:
            self._ips[address] = (
                await self.db.execute(select(Ip).where(Ip.address == address))
            ).scalar_one_or_none()
        return self._ips[address]

    async def subnet_by_cidr(self, cidr: str) -> Subnet | None:
        if cidr not in self._subnets_by_cidr:
            self._subnets_by_cidr[cidr] = (
                await self.db.execute(select(Subnet).where(Subnet.cidr == cidr))
            ).scalar_one_or_none()
        return self._subnets_by_cidr[cidr]

    async def link_by_ports(self, port_a_id: int, port_b_id: int) -> Link | None:
        key = (port_a_id, port_b_id)
        if key not in self._links:
            self._links[key] = (
                await self.db.execute(
                    select(Link).where(
                        Link.port_a_id == port_a_id, Link.port_b_id == port_b_id
                    )
                )
            ).scalar_one_or_none()
        return self._links[key]

    async def subnet_containing(self, address: IPv4Address) -> Subnet | None:
        """One table read per import instead of one per IP row."""
        if self._subnet_index is None:
            rows = (await self.db.execute(select(Subnet))).scalars().all()
            self._subnet_index = _SubnetIndex(rows)
        return self._subnet_index.find(address)

    # -- write-through -----------------------------------------------------
    #
    # A bulk import routinely creates an entity in one file and references it
    # from the next (`sites.csv` then `rooms.csv`). Registering creations here
    # is what keeps the memo honest: without it, the negative entry cached on
    # the first miss would outlive the INSERT and the later row would fail
    # with a bogus "not found".

    def remember_site(self, site: Site) -> None:
        self._sites[site.code] = site

    def remember_room(self, site_id: int, code: str, room: Room) -> None:
        self._rooms[(site_id, code)] = room

    def remember_vlan(self, vlan: Vlan) -> None:
        self._vlans[vlan.vlan_id] = vlan

    def remember_device(self, device: Device) -> None:
        self._devices[device.name] = device

    def remember_switch(self, switch: Switch) -> None:
        self._switches[switch.name] = switch

    def remember_ip(self, ip: Ip) -> None:
        self._ips[ip.address] = ip

    def remember_subnet(self, subnet: Subnet) -> None:
        self._subnets_by_cidr[subnet.cidr] = subnet

    def remember_link(self, port_a_id: int, port_b_id: int, link: Link) -> None:
        self._links[(port_a_id, port_b_id)] = link

    def forget_ports_of_switch(self, switch_id: int | None) -> None:
        """Drop the port memo for a switch whose port set just grew.

        Only the *negative* entries actually matter (a number that did not
        exist a moment ago now does), but dropping the whole switch is cheaper
        to reason about than filtering.
        """
        if switch_id is None:
            return
        for key in [k for k in self._ports if k[0] == switch_id]:
            del self._ports[key]

    def invalidate_subnet_index(self) -> None:
        """Called after any subnet upsert.

        Rebuilding lazily from the DB (rather than patching the index in
        place) keeps the snapshot exactly consistent with what a fresh scan
        would have seen, including server-side defaults and the canonical
        `CIDR` rendering Postgres hands back. The rebuild only happens if some
        later row actually needs a containment lookup, so a `subnets.csv` with
        5 000 rows still costs a single extra read.
        """
        self._subnet_index = None


# --------------------------------------------------------------------------- #
# Scope management
# --------------------------------------------------------------------------- #

_ACTIVE_CACHE: ContextVar[_RefCache | None] = ContextVar(
    "csv_import_ref_cache", default=None
)


@contextmanager
def _ref_cache_scope(db: AsyncSession) -> Iterator[_RefCache]:
    """Bind a fresh cache to the current context for the length of one import.

    The cache is torn down on exit — including on the rollback paths — so it
    can never be reused across transactions.
    """
    cache = _RefCache(db)
    token = _ACTIVE_CACHE.set(cache)
    try:
        yield cache
    finally:
        _ACTIVE_CACHE.reset(token)


def _refs(db: AsyncSession) -> _RefCache:
    """The cache for the running import, or a throwaway one.

    The `is db` guard means a cache can never serve rows read through a
    different session — and the throwaway fallback means calling a
    `_persist_*` helper on its own behaves exactly like the pre-cache code:
    one statement per lookup, nothing retained.
    """
    cache = _ACTIVE_CACHE.get()
    if cache is not None and cache.db is db:
        return cache
    return _RefCache(db)


# --------------------------------------------------------------------------- #
# Reference resolvers — small async helpers used by persist().
# --------------------------------------------------------------------------- #


async def _site_by_code(
    db: AsyncSession, code: str | None, column: str = "site_code"
) -> Site | None:
    if not code:
        return None
    site = await _refs(db).site_by_code(code)
    if site is None:
        raise _RefError(column, code, f"Site code {code!r} not found")
    return site


async def _room_by_codes(
    db: AsyncSession, site_code: str | None, room_code: str | None
) -> Room | None:
    if not site_code or not room_code:
        return None
    site = await _site_by_code(db, site_code, column="site_code")
    assert site is not None  # `site_code` is truthy here, so never None
    room = await _refs(db).room_by_code(site.id, room_code)
    if room is None:
        raise _RefError(
            "room_code", room_code, f"Room code {room_code!r} not found in site {site_code!r}"
        )
    return room


async def _vlan_by_id(
    db: AsyncSession, vlan_id: int | None, column: str = "vlan_id"
) -> Vlan | None:
    if vlan_id is None:
        return None
    vlan = await _refs(db).vlan_by_public_id(vlan_id)
    if vlan is None:
        raise _RefError(column, vlan_id, f"VLAN {vlan_id} not found")
    return vlan


async def _device_by_name(
    db: AsyncSession, name: str | None, column: str = "device_name"
) -> Device | None:
    if not name:
        return None
    device = await _refs(db).device_by_name(name)
    if device is None:
        raise _RefError(column, name, f"Device {name!r} not found")
    return device


async def _switch_by_name(db: AsyncSession, name: str, column: str) -> Switch:
    switch = await _refs(db).switch_by_name(name)
    if switch is None:
        raise _RefError(column, name, f"Switch {name!r} not found")
    return switch


async def _port_on_switch(
    db: AsyncSession, switch: Switch, number: int, column: str
) -> Port:
    port = await _refs(db).port_on_switch(switch.id, number)
    if port is None:
        raise _RefError(column, number, f"Port {number} not found on switch {switch.name!r}")
    return port


async def _find_subnet_for(db: AsyncSession, address: str) -> Subnet:
    """Locate the subnet whose CIDR contains the given address — used by the
    `ips` import which omits `subnet_id` from the CSV.

    Postgres-side equivalent would be `WHERE address << subnets.cidr`. Doing
    it in Python is fine: subnet rows are few (< 200) for realistic networks.

    The scan itself now goes through `_SubnetIndex` (see its docstring for the
    structure and for why the resolution order is preserved verbatim), so the
    subnets table is read once per import rather than once per IP row.
    """
    addr = IPv4Address(address)
    subnet = await _refs(db).subnet_containing(addr)
    if subnet is None:
        raise _RefError("address", address, f"No subnet contains {address}")
    return subnet
