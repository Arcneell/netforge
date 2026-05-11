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
        id=1, subnet_id=1, address="10.0.0.2",
        status=IpStatus.assigned, hostname="srv-01", description="DC primary",
    )
    db = _mock_db(_subnet(), ips=[ip])
    _, entries = await service.list_subnet_ips(db, 1)
    target = next(e for e in entries if e.address == "10.0.0.2")
    assert target.hostname == "srv-01"
    assert target.description == "DC primary"


@pytest.mark.asyncio
async def test_list_subnet_ips_refuses_huge_subnet() -> None:
    db = _mock_db(_subnet(cidr="10.0.0.0/8"), ips=[])
    with pytest.raises(HTTPException) as exc:
        await service.list_subnet_ips(db, 1)
    assert exc.value.detail["error"]["code"] == "SUBNET_TOO_LARGE"
