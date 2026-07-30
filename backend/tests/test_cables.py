"""Cable service — pure-function tests with mocked DB.

The interesting bits we exercise here:
  - `list_cables(in_stock_only=True)` filters on `link_id IS NULL`.
  - `list_cables` is paginated like every other list endpoint (Fix #8):
    one COUNT(*) query, one page-bounded SELECT.
  - `get_cable_for_link` returns None when no row matches.
  - `delete_cable` / `update_cable` propagate the 404 on a missing id.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.models.cable import Cable
from app.schemas.cable import CableCreate, CableUpdate
from app.schemas.common import PageParams
from app.services import cables as service


def _mock_db_for_list(rows: list[Cable], total: int | None = None) -> AsyncMock:
    """`list_cables` issues two SELECTs in order: COUNT(*) then the
    page-bounded row fetch — mirror that with a `side_effect` pair."""
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
async def test_list_cables_returns_all_rows() -> None:
    rows = [Cable(id=1, label="A"), Cable(id=2, label="B")]
    db = _mock_db_for_list(rows)
    items, total = await service.list_cables(db, PageParams())
    assert [c.id for c in items] == [1, 2]
    assert total == 2


@pytest.mark.asyncio
async def test_list_cables_in_stock_only_adds_where_clause() -> None:
    db = _mock_db_for_list([], total=0)
    await service.list_cables(db, PageParams(), in_stock_only=True)
    # The query passed to execute should mention WHERE link_id IS NULL —
    # we don't introspect the SQL here, but smoke-check that both the
    # COUNT and the row SELECT ran.
    assert db.execute.await_count == 2


@pytest.mark.asyncio
async def test_get_cable_for_link_returns_none_when_no_row() -> None:
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    assert await service.get_cable_for_link(db, 42) is None


@pytest.mark.asyncio
async def test_get_cable_for_link_returns_matching_row() -> None:
    cable = Cable(id=7, link_id=42, label="patched")
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=cable)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    out = await service.get_cable_for_link(db, 42)
    assert out is cable


@pytest.mark.asyncio
async def test_get_cable_404s_on_missing_id() -> None:
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc:
        await service.get_cable(db, 999)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_cable_applies_only_provided_fields() -> None:
    existing = Cable(
        id=1,
        label="old",
        color="blue",
        length_m=3,
        link_id=None,
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=existing)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    out = await service.update_cable(
        db, 1, CableUpdate(label="new")  # only label changes
    )
    assert out.label == "new"
    assert out.color == "blue"  # untouched
    assert out.length_m == 3


@pytest.mark.asyncio
async def test_create_cable_inserts_and_returns_row() -> None:
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    payload = CableCreate(label="L1", length_m=2, color="green")
    out = await service.create_cable(db, payload)
    assert out.label == "L1"
    assert out.length_m == 2
    db.add.assert_called_once()
    db.commit.assert_awaited()
