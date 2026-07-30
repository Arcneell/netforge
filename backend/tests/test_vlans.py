"""VLANs service — CRUD with mocked DB (Fix: no functional CRUD coverage
existed for VLANs, only the auth-guard smoke test). Mirrors the
`test_cables.py` pattern.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.models.vlan import Vlan
from app.schemas.common import PageParams
from app.schemas.vlan import VlanCreate, VlanUpdate
from app.services import vlans as service


def _mock_db_for_list(rows: list[Vlan], total: int | None = None) -> AsyncMock:
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=rows)
    row_result = MagicMock()
    row_result.scalars = MagicMock(return_value=scalars)

    count_result = MagicMock()
    count_result.scalar = MagicMock(return_value=total if total is not None else len(rows))

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[count_result, row_result])
    return db


def _fake_integrity_error(constraint: str) -> IntegrityError:
    orig = Exception(f'duplicate key value violates constraint "{constraint}"')
    return IntegrityError(statement="INSERT ...", params={}, orig=orig)


@pytest.mark.asyncio
async def test_list_vlans_returns_rows_and_total() -> None:
    rows = [Vlan(id=1, vlan_id=10, name="voice"), Vlan(id=2, vlan_id=20, name="data")]
    db = _mock_db_for_list(rows)
    items, total = await service.list_vlans(db, PageParams())
    assert [v.id for v in items] == [1, 2]
    assert total == 2


@pytest.mark.asyncio
async def test_list_vlans_respects_page_params() -> None:
    db = _mock_db_for_list([], total=0)
    await service.list_vlans(db, PageParams(page=2, page_size=10))
    assert db.execute.await_count == 2


@pytest.mark.asyncio
async def test_get_vlan_404s_on_missing_id() -> None:
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc:
        await service.get_vlan(db, 999)
    assert exc.value.status_code == 404
    assert exc.value.detail["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_create_vlan_inserts_and_returns_row() -> None:
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    payload = VlanCreate(vlan_id=100, name="servers")
    out = await service.create_vlan(db, payload)
    assert out.vlan_id == 100
    assert out.name == "servers"
    db.add.assert_called_once()
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_create_vlan_duplicate_vlan_id_maps_to_409() -> None:
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock(side_effect=_fake_integrity_error("vlans_vlan_id_key"))

    payload = VlanCreate(vlan_id=100, name="servers")
    with pytest.raises(HTTPException) as exc:
        await service.create_vlan(db, payload)
    assert exc.value.status_code == 409
    assert exc.value.detail["error"]["code"] == "DUPLICATE_VLAN_ID"


@pytest.mark.asyncio
async def test_create_vlan_out_of_range_maps_to_409() -> None:
    """The `vlans_id_range` CHECK constraint (1..4094) is DB-enforced;
    the Pydantic schema also validates `ge=1, le=4094` so this path is
    normally unreachable via the API, but the service must still map it
    correctly if it ever is (e.g. a future relaxed schema)."""
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock(side_effect=_fake_integrity_error("vlans_id_range"))

    payload = VlanCreate(vlan_id=100, name="servers")
    with pytest.raises(HTTPException) as exc:
        await service.create_vlan(db, payload)
    assert exc.value.status_code == 409
    assert exc.value.detail["error"]["code"] == "VLAN_ID_OUT_OF_RANGE"


@pytest.mark.asyncio
async def test_update_vlan_applies_only_provided_fields() -> None:
    existing = Vlan(id=1, vlan_id=100, name="old", color="#ff0000")
    db = AsyncMock()
    db.get = AsyncMock(return_value=existing)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    out = await service.update_vlan(db, 1, VlanUpdate(name="new"))
    assert out.name == "new"
    assert out.vlan_id == 100  # untouched
    assert out.color == "#ff0000"  # untouched


@pytest.mark.asyncio
async def test_update_vlan_404s_on_missing_id() -> None:
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc:
        await service.update_vlan(db, 999, VlanUpdate(name="x"))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_vlan_removes_row() -> None:
    vlan = Vlan(id=1, vlan_id=100, name="servers")
    db = AsyncMock()
    db.get = AsyncMock(return_value=vlan)
    db.delete = AsyncMock()
    db.commit = AsyncMock()

    await service.delete_vlan(db, 1)
    db.delete.assert_awaited_once_with(vlan)
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_delete_vlan_404s_on_missing_id() -> None:
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc:
        await service.delete_vlan(db, 999)
    assert exc.value.status_code == 404
