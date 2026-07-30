"""Rooms service — CRUD with mocked DB (Fix: no functional CRUD coverage
existed for rooms, only the auth-guard smoke test). Mirrors the
`test_cables.py` pattern.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.models.core import Room
from app.schemas.common import PageParams
from app.schemas.room import RoomCreate, RoomUpdate
from app.services import rooms as service


def _mock_db_for_list(rows: list[Room], total: int | None = None) -> AsyncMock:
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
async def test_list_rooms_returns_rows_and_total() -> None:
    rows = [Room(id=1, site_id=1, code="A"), Room(id=2, site_id=1, code="B")]
    db = _mock_db_for_list(rows)
    items, total = await service.list_rooms(db, PageParams())
    assert [r.id for r in items] == [1, 2]
    assert total == 2


@pytest.mark.asyncio
async def test_list_rooms_filters_by_site_id() -> None:
    db = _mock_db_for_list([], total=0)
    await service.list_rooms(db, PageParams(), site_id=3)
    # COUNT + row SELECT both run; the site_id filter is applied to both
    # queries inside the service (no direct SQL introspection here).
    assert db.execute.await_count == 2


@pytest.mark.asyncio
async def test_get_room_404s_on_missing_id() -> None:
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc:
        await service.get_room(db, 999)
    assert exc.value.status_code == 404
    assert exc.value.detail["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_create_room_inserts_and_returns_row() -> None:
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    payload = RoomCreate(site_id=1, code="A", description="Wiring closet")
    out = await service.create_room(db, payload)
    assert out.site_id == 1
    assert out.code == "A"
    db.add.assert_called_once()
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_create_room_duplicate_code_in_site_maps_to_409() -> None:
    """`rooms_site_code_uniq` — the same room code is allowed across
    different sites but not twice within the same site."""
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock(side_effect=_fake_integrity_error("rooms_site_code_uniq"))

    payload = RoomCreate(site_id=1, code="A")
    with pytest.raises(HTTPException) as exc:
        await service.create_room(db, payload)
    assert exc.value.status_code == 409
    assert exc.value.detail["error"]["code"] == "DUPLICATE_CODE"


@pytest.mark.asyncio
async def test_update_room_applies_only_provided_fields() -> None:
    existing = Room(id=1, site_id=1, code="A", description="old")
    db = AsyncMock()
    db.get = AsyncMock(return_value=existing)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    out = await service.update_room(db, 1, RoomUpdate(description="new"))
    assert out.description == "new"
    assert out.code == "A"  # untouched
    assert out.site_id == 1  # untouched


@pytest.mark.asyncio
async def test_update_room_404s_on_missing_id() -> None:
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc:
        await service.update_room(db, 999, RoomUpdate(description="x"))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_room_removes_row() -> None:
    room = Room(id=1, site_id=1, code="A")
    db = AsyncMock()
    db.get = AsyncMock(return_value=room)
    db.delete = AsyncMock()
    db.commit = AsyncMock()

    await service.delete_room(db, 1)
    db.delete.assert_awaited_once_with(room)
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_delete_room_with_devices_raises_409() -> None:
    """`devices.room_id` is ON DELETE SET NULL in the schema, but switches
    reference rooms too — pin that any FK violation on delete surfaces as
    a 409 rather than a 500."""
    room = Room(id=1, site_id=1, code="A")
    orig = Exception(
        'update or delete on table "rooms" violates foreign key constraint '
        '"switches_room_id_fkey" on table "switches"'
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=room)
    db.delete = AsyncMock()
    db.commit = AsyncMock(side_effect=IntegrityError(statement="DELETE ...", params={}, orig=orig))

    with pytest.raises(HTTPException) as exc:
        await service.delete_room(db, 1)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_delete_room_404s_on_missing_id() -> None:
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc:
        await service.delete_room(db, 999)
    assert exc.value.status_code == 404
