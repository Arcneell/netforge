"""Sites service — CRUD with mocked DB (Fix: functional CRUD coverage was
missing for sites/rooms/vlans/devices, only the auth-guard smoke test in
`test_crud_auth_guards.py` touched these routes).

Mirrors the `test_cables.py` / `test_vrfs.py` pattern: no real DB, just
`AsyncMock`/`MagicMock` standing in for the `AsyncSession`.

One behaviour pinned deliberately: `Site.rooms` no longer cascade-deletes
(see `app/models/core.py` and `test_model_cascades.py`), so deleting a site
that still has rooms must surface the DB's `ON DELETE RESTRICT` violation
as an `IntegrityError` that `delete_site` turns into a 409 — not a silent
cascade.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.models.core import Site
from app.schemas.common import PageParams
from app.schemas.site import SiteCreate, SiteUpdate
from app.services import sites as service


def _mock_db_for_list(rows: list[Site], total: int | None = None) -> AsyncMock:
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


def _fake_fk_restrict_error() -> IntegrityError:
    orig = Exception(
        'update or delete on table "sites" violates foreign key constraint '
        '"rooms_site_id_fkey" on table "rooms"'
    )
    return IntegrityError(statement="DELETE ...", params={}, orig=orig)


@pytest.mark.asyncio
async def test_list_sites_returns_rows_and_total() -> None:
    rows = [Site(id=1, code="HQ", name="Headquarters"), Site(id=2, code="DC1", name="Datacenter 1")]
    db = _mock_db_for_list(rows)
    items, total = await service.list_sites(db, PageParams())
    assert [s.id for s in items] == [1, 2]
    assert total == 2


@pytest.mark.asyncio
async def test_list_sites_respects_page_params() -> None:
    db = _mock_db_for_list([], total=0)
    await service.list_sites(db, PageParams(page=2, page_size=10))
    assert db.execute.await_count == 2


@pytest.mark.asyncio
async def test_get_site_404s_on_missing_id() -> None:
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc:
        await service.get_site(db, 999)
    assert exc.value.status_code == 404
    assert exc.value.detail["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_get_site_returns_existing_row() -> None:
    site = Site(id=1, code="HQ", name="Headquarters")
    db = AsyncMock()
    db.get = AsyncMock(return_value=site)
    out = await service.get_site(db, 1)
    assert out is site


@pytest.mark.asyncio
async def test_create_site_inserts_and_returns_row() -> None:
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    payload = SiteCreate(code="HQ", name="Headquarters")
    out = await service.create_site(db, payload)
    assert out.code == "HQ"
    assert out.name == "Headquarters"
    db.add.assert_called_once()
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_create_site_duplicate_code_maps_to_409() -> None:
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock(side_effect=_fake_integrity_error("sites_code_key"))

    payload = SiteCreate(code="HQ", name="Headquarters")
    with pytest.raises(HTTPException) as exc:
        await service.create_site(db, payload)
    assert exc.value.status_code == 409
    assert exc.value.detail["error"]["code"] == "DUPLICATE_CODE"


@pytest.mark.asyncio
async def test_update_site_applies_only_provided_fields() -> None:
    existing = Site(id=1, code="HQ", name="Old Name", address="123 Main St")
    db = AsyncMock()
    db.get = AsyncMock(return_value=existing)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    out = await service.update_site(db, 1, SiteUpdate(name="New Name"))
    assert out.name == "New Name"
    assert out.code == "HQ"  # untouched
    assert out.address == "123 Main St"  # untouched


@pytest.mark.asyncio
async def test_update_site_404s_on_missing_id() -> None:
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc:
        await service.update_site(db, 999, SiteUpdate(name="X"))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_site_removes_row() -> None:
    site = Site(id=1, code="HQ", name="Headquarters")
    db = AsyncMock()
    db.get = AsyncMock(return_value=site)
    db.delete = AsyncMock()
    db.commit = AsyncMock()

    await service.delete_site(db, 1)
    db.delete.assert_awaited_once_with(site)
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_delete_site_with_rooms_raises_409_not_cascade() -> None:
    """`Site.rooms` has no ORM delete cascade (RESTRICT at the FK level).
    The service must let the DB's IntegrityError surface as a 409 rather
    than silently deleting the site's rooms."""
    site = Site(id=1, code="HQ", name="Headquarters")
    db = AsyncMock()
    db.get = AsyncMock(return_value=site)
    db.delete = AsyncMock()
    db.commit = AsyncMock(side_effect=_fake_fk_restrict_error())

    with pytest.raises(HTTPException) as exc:
        await service.delete_site(db, 1)
    assert exc.value.status_code == 409
    # Not one of the named constraints in _CONSTRAINT_CODES — falls back to
    # the generic integrity-violation code, which is still a 409 (not a 500,
    # and not a silent success).
    assert exc.value.detail["error"]["code"] == "INTEGRITY_VIOLATION"


@pytest.mark.asyncio
async def test_delete_site_404s_on_missing_id() -> None:
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc:
        await service.delete_site(db, 999)
    assert exc.value.status_code == 404
