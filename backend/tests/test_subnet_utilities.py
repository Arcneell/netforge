"""Tests for the subnet utility endpoints (phase 4).

Pure-function tests on the service layer with a hand-rolled mock session —
no real DB required. The service iterates `IPv4Network.hosts()` and skips
gateway + assigned addresses; we verify the algorithm exhaustively on a tiny
network.
"""

from __future__ import annotations

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


@pytest.mark.asyncio
async def test_per_subnet_used_counts_strips_inet_mask() -> None:
    """asyncpg decodes INET to IPv4Interface, whose `str()` returns
    `'10.0.0.0/32'`. The boundary check must canonicalise back to the
    bare dotted-quad before matching against the in-memory boundary set
    — otherwise the subtract silently misses every row (Codex P1 on #76).
    """
    sub = Subnet(id=1, cidr="10.0.0.0/24", site_id=1, dhcp_enabled=False)
    db = _mock_db_for_per_subnet_counts(
        raw_counts=[(1, 5)],
        # Simulate asyncpg returning the inet value with its /32 mask.
        boundary_rows=[(1, "10.0.0.255/32")],
    )
    counts = await service._per_subnet_used_counts(db, [sub])
    assert counts == {1: 4}
