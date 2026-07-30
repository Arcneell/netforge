"""Tests for the subnet utility endpoints (phase 4).

Pure-function tests on the service layer with a hand-rolled mock session —
no real DB required. The service iterates `IPv4Network.hosts()` and skips
gateway + assigned addresses; we verify the algorithm exhaustively on a tiny
network.
"""

from __future__ import annotations

from ipaddress import IPv4Interface
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.models.ip import Ip, IpStatus
from app.models.subnet import Subnet
from app.services import subnets as service


def _mock_db(subnet: Subnet, ips: list[Ip]) -> AsyncMock:
    """Mock DB where db.get → subnet, db.execute(select(Ip)) → ips."""
    ips_scalars = MagicMock()
    ips_scalars.all = MagicMock(return_value=ips)

    ips_result = MagicMock()
    ips_result.scalars = MagicMock(return_value=ips_scalars)

    db = AsyncMock()
    db.get = AsyncMock(return_value=subnet)
    db.execute = AsyncMock(return_value=ips_result)
    return db


# Small /29 → 6 host addresses: .1, .2, .3, .4, .5, .6
_TINY_CIDR = "10.0.0.0/29"


def _subnet(cidr: str = _TINY_CIDR, gateway: str | None = "10.0.0.1") -> Subnet:
    return Subnet(id=1, cidr=cidr, gateway=gateway, site_id=1, dhcp_enabled=False)


def _ip(address: str, status: IpStatus = IpStatus.assigned) -> Ip:
    return Ip(id=1, subnet_id=1, address=address, status=status)


# --- next_free_ip ----------------------------------------------------------


@pytest.mark.asyncio
async def test_next_free_skips_gateway_and_returns_first_free() -> None:
    db = _mock_db(_subnet(), ips=[])
    assert await service.next_free_ip(db, 1) == "10.0.0.2"


@pytest.mark.asyncio
async def test_next_free_skips_already_assigned() -> None:
    db = _mock_db(_subnet(), ips=[_ip("10.0.0.2"), _ip("10.0.0.3")])
    assert await service.next_free_ip(db, 1) == "10.0.0.4"


@pytest.mark.asyncio
async def test_next_free_returns_first_when_no_gateway_set() -> None:
    db = _mock_db(_subnet(gateway=None), ips=[])
    assert await service.next_free_ip(db, 1) == "10.0.0.1"


@pytest.mark.asyncio
async def test_next_free_skips_ips_with_asyncpg_ipv4interface_address() -> None:
    """asyncpg decodes INET to IPv4Interface, so `ip.address` is an
    IPv4Interface at runtime and `str(...)` returns "10.0.0.2/32". A naive
    `{str(ip.address): ip}` lookup against `str(host)` from
    `IPv4Network.hosts()` always misses — `next_free_ip` then returns an
    address that already has a row in `ips` (silently handing out
    duplicates). This pins the canonical-string contract through
    `_ip_text()`.
    """
    db = _mock_db(
        _subnet(),
        ips=[Ip(id=1, subnet_id=1, address=IPv4Interface("10.0.0.2/32"))],
    )
    # .1 is the gateway, .2 is "used" via IPv4Interface → first free is .3
    assert await service.next_free_ip(db, 1) == "10.0.0.3"


@pytest.mark.asyncio
async def test_next_free_handles_asyncpg_ipv4interface_gateway() -> None:
    """`subnet.gateway` is INET → asyncpg returns IPv4Interface, whose
    str() form is "10.0.0.1/32". The old code did `IPv4Address(gw)` which
    raised `AddressValueError` on that mask suffix and 500'd every
    `POST /api/subnets/{id}/next-free` against a subnet that has a
    gateway set.
    """
    subnet = Subnet(
        id=1,
        cidr="10.0.0.0/29",
        gateway=IPv4Interface("10.0.0.1/32"),
        site_id=1,
        dhcp_enabled=False,
    )
    db = _mock_db(subnet, ips=[])
    # Gateway .1 is skipped — first free is .2
    assert await service.next_free_ip(db, 1) == "10.0.0.2"


@pytest.mark.asyncio
async def test_next_free_skips_dhcp_range_with_asyncpg_interfaces() -> None:
    """Same problem as gateway: `dhcp_range_start` / `dhcp_range_end`
    come back as IPv4Interface, so `_dhcp_bounds` must canonicalise
    them before constructing IPv4Address objects for the bounds check.
    """
    subnet = Subnet(
        id=1,
        cidr="10.0.0.0/29",
        gateway=None,
        site_id=1,
        dhcp_enabled=True,
        dhcp_range_start=IPv4Interface("10.0.0.1/32"),
        dhcp_range_end=IPv4Interface("10.0.0.3/32"),
    )
    db = _mock_db(subnet, ips=[])
    # .1 .. .3 in DHCP pool → first free is .4
    assert await service.next_free_ip(db, 1) == "10.0.0.4"


@pytest.mark.asyncio
async def test_next_free_raises_subnet_full_when_exhausted() -> None:
    # gateway .1 + 5 assigned = all 6 hosts used
    ips = [_ip(f"10.0.0.{i}") for i in range(2, 7)]
    db = _mock_db(_subnet(), ips=ips)
    with pytest.raises(HTTPException) as exc:
        await service.next_free_ip(db, 1)
    assert exc.value.status_code == 400
    assert exc.value.detail["error"]["code"] == "SUBNET_FULL"


@pytest.mark.asyncio
async def test_next_free_refuses_huge_subnet() -> None:
    db = _mock_db(_subnet(cidr="10.0.0.0/8", gateway=None), ips=[])
    with pytest.raises(HTTPException) as exc:
        await service.next_free_ip(db, 1)
    assert exc.value.status_code == 400
    assert exc.value.detail["error"]["code"] == "SUBNET_TOO_LARGE"


# --- list_subnet_ips -------------------------------------------------------


@pytest.mark.asyncio
async def test_list_subnet_ips_returns_every_host_with_status() -> None:
    db = _mock_db(_subnet(), ips=[_ip("10.0.0.3", IpStatus.assigned)])
    _subnet_obj, entries = await service.list_subnet_ips(db, 1)

    # /29 → 6 host addresses
    assert [e.address for e in entries] == [
        "10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4", "10.0.0.5", "10.0.0.6",
    ]
    # Only .3 is assigned; the gateway .1 remains "free" — listing does not
    # alter status (only next_free_ip skips it for allocation).
    statuses = {e.address: e.status for e in entries}
    assert statuses["10.0.0.3"] == "assigned"
    assert statuses["10.0.0.2"] == "free"
    assert statuses["10.0.0.1"] == "free"


@pytest.mark.asyncio
async def test_list_subnet_ips_carries_hostname_and_description() -> None:
    ip = Ip(
        id=42, subnet_id=1, address="10.0.0.2",
        status=IpStatus.assigned, hostname="srv-01", description="DC primary",
    )
    db = _mock_db(_subnet(), ips=[ip])
    _, entries = await service.list_subnet_ips(db, 1)
    target = next(e for e in entries if e.address == "10.0.0.2")
    assert target.hostname == "srv-01"
    assert target.description == "DC primary"
    # PR perf/ipam-indexes-and-group-by: every entry backed by a real Ip
    # row carries its `id` so the editor opens with one fetch instead of
    # round-tripping through `/ips?q=...`. Synthetic free/dhcp rows keep
    # `ip_id = None`.
    assert target.ip_id == 42
    free_entry = next(e for e in entries if e.address == "10.0.0.1")
    assert free_entry.status == "free"
    assert free_entry.ip_id is None


@pytest.mark.asyncio
async def test_list_subnet_ips_refuses_huge_subnet() -> None:
    db = _mock_db(_subnet(cidr="10.0.0.0/8"), ips=[])
    with pytest.raises(HTTPException) as exc:
        await service.list_subnet_ips(db, 1)
    assert exc.value.detail["error"]["code"] == "SUBNET_TOO_LARGE"


# --- compute_utilization ----------------------------------------------------


def _mock_db_for_utilization(subnet: Subnet, status_counts: dict[str, int]) -> AsyncMock:
    """Mock DB where execute returns aggregate (status, count) tuples."""
    rows = [(IpStatus(k), v) for k, v in status_counts.items()]
    result = MagicMock()
    result.all = MagicMock(return_value=rows)
    db = AsyncMock()
    db.get = AsyncMock(return_value=subnet)
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.asyncio
async def test_compute_utilization_on_slash_24() -> None:
    """/24 has 254 usable hosts. With 100 assigned + 20 dhcp + 5 reserved
    we get 125 used and free = 129. used_pct = 125 * 100 // 254 = 49."""
    db = _mock_db_for_utilization(
        _subnet(cidr="10.0.0.0/24"),
        {"assigned": 100, "dhcp": 20, "reserved": 5},
    )
    _, util = await service.compute_utilization(db, 1)
    assert util["usable"] == 254
    assert util["status_assigned"] == 100
    assert util["status_dhcp"] == 20
    assert util["status_reserved"] == 5
    assert util["free"] == 129  # 254 - 125
    assert util["used_pct"] == 49  # 125 * 100 // 254


@pytest.mark.asyncio
async def test_compute_utilization_handles_slash_31() -> None:
    """RFC 3021 /31 keeps both addresses as usable (no network/broadcast).
    Two assigned IPs → 100% used. Without the /31 special case we'd report
    `usable = 0` and a divide-by-zero — pinned so a refactor can't break it."""
    db = _mock_db_for_utilization(
        _subnet(cidr="10.0.0.0/31", gateway=None),
        {"assigned": 2},
    )
    _, util = await service.compute_utilization(db, 1)
    assert util["usable"] == 2
    assert util["free"] == 0
    assert util["used_pct"] == 100


@pytest.mark.asyncio
async def test_compute_utilization_works_on_large_subnet() -> None:
    """Unlike `list_subnet_ips`, the utilisation endpoint does not refuse
    on /16-and-up — it never enumerates the address space, just aggregates
    counts. Operators must be able to see their fill rate on a /16."""
    db = _mock_db_for_utilization(
        _subnet(cidr="10.0.0.0/16", gateway=None),
        {"assigned": 50_000},
    )
    _, util = await service.compute_utilization(db, 1)
    assert util["usable"] == 65_534  # 2**16 - 2
    assert util["status_assigned"] == 50_000
    assert util["used_pct"] == 76  # 50000 * 100 // 65534


# --- _per_subnet_used_counts (PR perf/ipam-indexes-and-group-by) ------------


def _mock_db_for_per_subnet_counts(
    raw_counts: list[tuple[int, int]],
    boundary_rows: list[tuple[int, str]],
) -> AsyncMock:
    """Mock the two grouped SELECTs that `_per_subnet_used_counts` issues:
    a raw `(subnet_id, COUNT(*))` then a per-row boundary subtract."""
    raw_result = MagicMock()
    raw_result.all = MagicMock(return_value=raw_counts)
    boundary_result = MagicMock()
    boundary_result.all = MagicMock(return_value=boundary_rows)
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[raw_result, boundary_result])
    return db


@pytest.mark.asyncio
async def test_per_subnet_used_counts_empty_input_skips_queries() -> None:
    """Empty input must not fire any SQL — IN ()-clauses are an asyncpg error
    and the cheapest correct answer is `{}`."""
    db = AsyncMock()
    db.execute = AsyncMock()
    out = await service._per_subnet_used_counts(db, [])
    assert out == {}
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_per_subnet_used_counts_subtracts_boundary_addresses() -> None:
    """A /24 with 5 IP rows of which one lives on the broadcast (.255)
    should report used = 4. Without the subtract we'd return 5 and the
    fill bar would disagree with `compute_utilization`."""
    sub = Subnet(id=1, cidr="10.0.0.0/24", site_id=1, dhcp_enabled=False)
    db = _mock_db_for_per_subnet_counts(
        raw_counts=[(1, 5)],
        boundary_rows=[(1, "10.0.0.255")],
    )
    counts = await service._per_subnet_used_counts(db, [sub])
    assert counts == {1: 4}


@pytest.mark.asyncio
async def test_per_subnet_used_counts_clamps_below_zero() -> None:
    """Defensive clamp: if the boundary subtract somehow overshoots the
    raw count (unexpected DB state), we surface 0 rather than -N so the
    UI never displays a negative fill."""
    sub = Subnet(id=1, cidr="10.0.0.0/24", site_id=1, dhcp_enabled=False)
    db = _mock_db_for_per_subnet_counts(
        raw_counts=[(1, 1)],
        boundary_rows=[(1, "10.0.0.0"), (1, "10.0.0.255")],
    )
    counts = await service._per_subnet_used_counts(db, [sub])
    assert counts == {1: 0}


@pytest.mark.asyncio
async def test_per_subnet_used_counts_keeps_slash_31_rows() -> None:
    """RFC 3021 /31s have no network/broadcast — both addresses are
    host-usable. The helper must NOT add them to the boundary set, so a
    /31 with 2 IP rows keeps used = 2."""
    sub = Subnet(id=7, cidr="10.0.0.0/31", site_id=1, dhcp_enabled=False)
    db = _mock_db_for_per_subnet_counts(
        raw_counts=[(7, 2)],
        boundary_rows=[],
    )
    counts = await service._per_subnet_used_counts(db, [sub])
    assert counts == {7: 2}


# --- capacity_overview (PR feat/dashboard-capacity-heatmap) ----------------


def _mock_db_for_capacity(
    subnets: list[Subnet],
    raw_counts: list[tuple[int, int]],
    boundary_rows: list[tuple[int, str]] | None = None,
) -> AsyncMock:
    """Mock the SELECTs `capacity_overview` issues:
      1. `SELECT * FROM subnets`
      2. raw GROUP BY count (from `_per_subnet_used_counts`)
      3. boundary subtract (skipped if there are no /≤30 prefixes)
    """
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=subnets)
    subnets_result = MagicMock()
    subnets_result.scalars = MagicMock(return_value=scalars)

    raw_result = MagicMock()
    raw_result.all = MagicMock(return_value=raw_counts)
    boundary_result = MagicMock()
    boundary_result.all = MagicMock(return_value=list(boundary_rows or []))

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[subnets_result, raw_result, boundary_result]
    )
    return db


@pytest.mark.asyncio
async def test_capacity_overview_ranks_buckets() -> None:
    """Three /24s: one nearly full, one full, one untouched. The overview
    must drop each into the matching bucket without duplicates."""
    nearly_full = Subnet(id=1, cidr="10.0.0.0/24", site_id=1, dhcp_enabled=False)
    full = Subnet(id=2, cidr="10.0.1.0/24", site_id=1, dhcp_enabled=False)
    empty = Subnet(id=3, cidr="10.0.2.0/24", site_id=1, dhcp_enabled=False)
    db = _mock_db_for_capacity(
        subnets=[nearly_full, full, empty],
        raw_counts=[(1, 230), (2, 254)],
        boundary_rows=[],
    )
    out = await service.capacity_overview(db, limit=5)
    assert out["total_subnets"] == 3
    assert [e["id"] for e in out["fullest"]] == [1]    # 230/254 ≈ 90%
    assert [e["id"] for e in out["full"]] == [2]       # 254/254 = 100%
    assert [e["id"] for e in out["unused"]] == [3]


@pytest.mark.asyncio
async def test_capacity_overview_respects_limit() -> None:
    """When more than `limit` subnets qualify, only the top `limit` per
    bucket come back. Sorted by pct desc, ties broken by `used`."""
    subnets = [
        Subnet(id=i, cidr=f"10.0.{i}.0/24", site_id=1, dhcp_enabled=False)
        for i in range(1, 6)
    ]
    # 200 / 254 = 78% — under the 80% gate, drops out of `fullest`.
    # 210→82%, 220→86%, 230→90%, 240→94% — all four make the cut.
    raw = [(1, 200), (2, 210), (3, 220), (4, 230), (5, 240)]
    db = _mock_db_for_capacity(subnets, raw_counts=raw, boundary_rows=[])
    out = await service.capacity_overview(db, limit=3)
    assert [e["id"] for e in out["fullest"]] == [5, 4, 3]


@pytest.mark.asyncio
async def test_capacity_overview_empty_inventory() -> None:
    """No subnets means every bucket is empty — must not raise."""
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=[])
    subnets_result = MagicMock()
    subnets_result.scalars = MagicMock(return_value=scalars)
    db = AsyncMock()
    # Empty list of subnets short-circuits `_per_subnet_used_counts` →
    # no second SELECT, only the initial fetch.
    db.execute = AsyncMock(side_effect=[subnets_result])
    out = await service.capacity_overview(db, limit=5)
    assert out == {"fullest": [], "full": [], "unused": [], "total_subnets": 0}


# --- _validate_dhcp_range: start <= end (Fix #6) ---------------------------


def test_validate_dhcp_range_accepts_start_before_end() -> None:
    # Should not raise.
    service._validate_dhcp_range(
        "10.0.0.0/24",
        {"dhcp_range_start": "10.0.0.10", "dhcp_range_end": "10.0.0.50"},
    )


def test_validate_dhcp_range_accepts_start_equal_end() -> None:
    """A single-address pool is a degenerate but valid range."""
    service._validate_dhcp_range(
        "10.0.0.0/24",
        {"dhcp_range_start": "10.0.0.10", "dhcp_range_end": "10.0.0.10"},
    )


def test_validate_dhcp_range_rejects_start_after_end() -> None:
    with pytest.raises(HTTPException) as exc:
        service._validate_dhcp_range(
            "10.0.0.0/24",
            {"dhcp_range_start": "10.0.0.50", "dhcp_range_end": "10.0.0.10"},
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["error"]["code"] == "INVALID_DHCP_RANGE"


def test_validate_dhcp_range_skips_check_when_only_one_bound_set() -> None:
    # Only `dhcp_range_start` present — nothing to compare against, must
    # not raise.
    service._validate_dhcp_range("10.0.0.0/24", {"dhcp_range_start": "10.0.0.50"})


def test_validate_dhcp_range_still_rejects_out_of_subnet_bounds_first() -> None:
    """The existing "inside the CIDR" check must still fire even though the
    new start<=end check was added — pins the two validations don't shadow
    each other."""
    with pytest.raises(HTTPException) as exc:
        service._validate_dhcp_range(
            "10.0.0.0/24",
            {"dhcp_range_start": "10.0.0.10", "dhcp_range_end": "192.168.0.1"},
        )
    assert exc.value.detail["error"]["code"] == "ADDRESS_OUT_OF_SUBNET"
