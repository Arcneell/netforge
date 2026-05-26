"""Unit tests for the bulk IP range endpoint.

Pure-function tests on the service layer with a hand-rolled mock session —
no real DB required. The bulk path is intentionally chatty (one in-range
SELECT + per-address INSERT / UPDATE / DELETE), so we pin the four core
behaviours: reserve a fresh range, skip existing, overwrite with the flag,
and release.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.models.ip import Ip, IpStatus
from app.models.subnet import Subnet
from app.schemas.ip import BulkIpAction, BulkIpRange
from app.services import ips as service


def _subnet() -> Subnet:
    return Subnet(id=1, cidr="10.0.0.0/24", site_id=1, dhcp_enabled=False)


def _mock_db(subnet: Subnet, existing: list[Ip]) -> AsyncMock:
    """db.get(Subnet) → subnet, db.execute(SELECT Ip...) → existing list."""
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=existing)
    existing_result = MagicMock()
    existing_result.scalars = MagicMock(return_value=scalars)

    db = AsyncMock()
    db.get = AsyncMock(return_value=subnet)
    db.execute = AsyncMock(return_value=existing_result)
    db.add = MagicMock()
    db.delete = AsyncMock()
    db.commit = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_bulk_reserve_creates_rows_for_empty_range() -> None:
    """No existing rows → every host in the range is created."""
    db = _mock_db(_subnet(), existing=[])
    payload = BulkIpRange(
        action=BulkIpAction.reserve,
        start="10.0.0.10",
        end="10.0.0.13",
    )
    out = await service.bulk_ip_range(db, 1, payload)
    assert out == {
        "requested": 4,
        "created": 4,
        "updated": 0,
        "deleted": 0,
        "skipped": 0,
    }
    # 4 INSERTs queued on the session; commit fires exactly once at the end.
    assert db.add.call_count == 4
    assert db.commit.await_count == 1


@pytest.mark.asyncio
async def test_bulk_reserve_skips_existing_without_overwrite() -> None:
    """Existing rows are left alone; the count tracks how many were skipped."""
    existing = [
        Ip(id=1, subnet_id=1, address="10.0.0.11", status=IpStatus.assigned),
    ]
    db = _mock_db(_subnet(), existing=existing)
    payload = BulkIpRange(
        action=BulkIpAction.reserve,
        start="10.0.0.10",
        end="10.0.0.13",
    )
    out = await service.bulk_ip_range(db, 1, payload)
    assert out["created"] == 3
    assert out["skipped"] == 1
    assert out["updated"] == 0


@pytest.mark.asyncio
async def test_bulk_reserve_overwrites_with_flag() -> None:
    """`overwrite=True` flips existing rows to the requested status in place."""
    existing = [
        Ip(id=1, subnet_id=1, address="10.0.0.11", status=IpStatus.assigned),
    ]
    db = _mock_db(_subnet(), existing=existing)
    payload = BulkIpRange(
        action=BulkIpAction.reserve,
        start="10.0.0.10",
        end="10.0.0.13",
        status=IpStatus.reserved,
        overwrite=True,
    )
    out = await service.bulk_ip_range(db, 1, payload)
    assert out["created"] == 3
    assert out["updated"] == 1
    assert out["skipped"] == 0
    assert existing[0].status == IpStatus.reserved


@pytest.mark.asyncio
async def test_bulk_release_deletes_existing_rows_only() -> None:
    """Release deletes the rows it finds, skips the addresses without rows."""
    existing = [
        Ip(id=1, subnet_id=1, address="10.0.0.11", status=IpStatus.assigned),
        Ip(id=2, subnet_id=1, address="10.0.0.13", status=IpStatus.reserved),
    ]
    db = _mock_db(_subnet(), existing=existing)
    payload = BulkIpRange(
        action=BulkIpAction.release,
        start="10.0.0.10",
        end="10.0.0.13",
    )
    out = await service.bulk_ip_range(db, 1, payload)
    assert out["deleted"] == 2
    assert out["skipped"] == 2  # .10 and .12 had no row
    assert db.delete.await_count == 2


@pytest.mark.asyncio
async def test_bulk_skips_boundary_addresses_on_slash_24() -> None:
    """Network / broadcast slots are silently excluded from the range so
    the bulk count never disagrees with `_per_subnet_used_counts`."""
    db = _mock_db(_subnet(), existing=[])
    payload = BulkIpRange(
        action=BulkIpAction.reserve,
        start="10.0.0.0",  # network — must be skipped
        end="10.0.0.2",
    )
    out = await service.bulk_ip_range(db, 1, payload)
    # Range covers 3 addresses; only .1 and .2 actually get a row.
    assert out["requested"] == 3
    assert out["created"] == 2
    # The skipped count surfaces the boundary so the UI can hint at it.
    assert out["skipped"] == 1


@pytest.mark.asyncio
async def test_bulk_rejects_reversed_range() -> None:
    db = _mock_db(_subnet(), existing=[])
    payload = BulkIpRange(
        action=BulkIpAction.reserve,
        start="10.0.0.20",
        end="10.0.0.10",
    )
    with pytest.raises(HTTPException) as exc:
        await service.bulk_ip_range(db, 1, payload)
    assert exc.value.detail["error"]["code"] == "INVALID_RANGE"


@pytest.mark.asyncio
async def test_bulk_rejects_range_outside_subnet() -> None:
    db = _mock_db(_subnet(), existing=[])
    payload = BulkIpRange(
        action=BulkIpAction.reserve,
        start="10.0.0.10",
        end="10.0.1.10",  # falls outside 10.0.0.0/24
    )
    with pytest.raises(HTTPException) as exc:
        await service.bulk_ip_range(db, 1, payload)
    assert exc.value.detail["error"]["code"] == "IP_NOT_IN_SUBNET"


@pytest.mark.asyncio
async def test_bulk_rejects_oversize_range() -> None:
    """Cap is set so a /23 sweep splits into two halves rather than one
    runaway transaction."""
    # Bigger subnet so the range can plausibly land in it.
    big_subnet = Subnet(id=1, cidr="10.0.0.0/22", site_id=1, dhcp_enabled=False)
    db = _mock_db(big_subnet, existing=[])
    payload = BulkIpRange(
        action=BulkIpAction.reserve,
        start="10.0.0.1",
        end="10.0.3.254",
    )
    with pytest.raises(HTTPException) as exc:
        await service.bulk_ip_range(db, 1, payload)
    assert exc.value.detail["error"]["code"] == "BULK_RANGE_TOO_LARGE"


@pytest.mark.asyncio
async def test_bulk_rejects_missing_subnet() -> None:
    db = _mock_db(_subnet(), existing=[])
    db.get = AsyncMock(return_value=None)
    payload = BulkIpRange(
        action=BulkIpAction.reserve,
        start="10.0.0.10",
        end="10.0.0.13",
    )
    with pytest.raises(HTTPException) as exc:
        await service.bulk_ip_range(db, 99, payload)
    assert exc.value.status_code == 404
