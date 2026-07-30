"""Devices service — CRUD with mocked DB (Fix: no functional CRUD coverage
existed for devices, only the auth-guard smoke test). Mirrors the
`test_cables.py` pattern.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.models.device import Device
from app.schemas.common import PageParams
from app.schemas.device import DeviceCreate, DeviceType, DeviceUpdate
from app.services import devices as service


def _mock_db_for_list(rows: list[Device], total: int | None = None) -> AsyncMock:
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=rows)
    row_result = MagicMock()
    row_result.scalars = MagicMock(return_value=scalars)

    count_result = MagicMock()
    count_result.scalar = MagicMock(return_value=total if total is not None else len(rows))

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[count_result, row_result])
    return db


@pytest.mark.asyncio
async def test_list_devices_returns_rows_and_total() -> None:
    rows = [
        Device(id=1, name="srv-01", type=DeviceType.server),
        Device(id=2, name="srv-02", type=DeviceType.server),
    ]
    db = _mock_db_for_list(rows)
    items, total = await service.list_devices(db, PageParams())
    assert [d.id for d in items] == [1, 2]
    assert total == 2


@pytest.mark.asyncio
async def test_list_devices_filters_by_type() -> None:
    db = _mock_db_for_list([], total=0)
    await service.list_devices(db, PageParams(), type_=DeviceType.printer)
    assert db.execute.await_count == 2


@pytest.mark.asyncio
async def test_list_devices_filters_by_room_id() -> None:
    db = _mock_db_for_list([], total=0)
    await service.list_devices(db, PageParams(), room_id=5)
    assert db.execute.await_count == 2


@pytest.mark.asyncio
async def test_list_devices_filters_by_search_query() -> None:
    db = _mock_db_for_list([], total=0)
    await service.list_devices(db, PageParams(), q="srv")
    assert db.execute.await_count == 2


@pytest.mark.asyncio
async def test_get_device_404s_on_missing_id() -> None:
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc:
        await service.get_device(db, 999)
    assert exc.value.status_code == 404
    assert exc.value.detail["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_create_device_inserts_and_returns_row() -> None:
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    payload = DeviceCreate(name="srv-01", type=DeviceType.server)
    out = await service.create_device(db, payload)
    assert out.name == "srv-01"
    assert out.type == DeviceType.server
    db.add.assert_called_once()
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_update_device_applies_only_provided_fields() -> None:
    existing = Device(id=1, name="old-name", type=DeviceType.server, vendor="Dell")
    db = AsyncMock()
    db.get = AsyncMock(return_value=existing)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    out = await service.update_device(db, 1, DeviceUpdate(name="new-name"))
    assert out.name == "new-name"
    assert out.type == DeviceType.server  # untouched
    assert out.vendor == "Dell"  # untouched


@pytest.mark.asyncio
async def test_update_device_404s_on_missing_id() -> None:
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc:
        await service.update_device(db, 999, DeviceUpdate(name="x"))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_device_removes_row() -> None:
    device = Device(id=1, name="srv-01", type=DeviceType.server)
    db = AsyncMock()
    db.get = AsyncMock(return_value=device)
    db.delete = AsyncMock()
    db.commit = AsyncMock()

    await service.delete_device(db, 1)
    db.delete.assert_awaited_once_with(device)
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_delete_device_404s_on_missing_id() -> None:
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc:
        await service.delete_device(db, 999)
    assert exc.value.status_code == 404
