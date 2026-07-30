"""VRF service — pagination (Fix #8: /api/vrfs had no Page[T] like the
rest of the CRUD surface). Pure-function tests with a mocked DB.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.vrf import Vrf
from app.schemas.common import PageParams
from app.services import vrfs as service


def _mock_db_for_list(rows: list[Vrf], total: int | None = None) -> AsyncMock:
    """`list_vrfs` issues two SELECTs in order: COUNT(*) then the
    page-bounded row fetch."""
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
async def test_list_vrfs_returns_rows_and_total() -> None:
    rows = [Vrf(id=1, name="prod"), Vrf(id=2, name="dev")]
    db = _mock_db_for_list(rows)
    items, total = await service.list_vrfs(db, PageParams())
    assert [v.id for v in items] == [1, 2]
    assert total == 2


@pytest.mark.asyncio
async def test_list_vrfs_respects_page_params() -> None:
    db = _mock_db_for_list([], total=0)
    await service.list_vrfs(db, PageParams(page=2, page_size=10))
    # COUNT + row SELECT — both must run regardless of page.
    assert db.execute.await_count == 2
