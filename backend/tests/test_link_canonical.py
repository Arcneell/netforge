"""Verify that the link service swaps endpoints to keep the canonical order
required by the CHECK constraint (port_a_id < port_b_id).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.link import Link
from app.models.port import Port
from app.schemas.link import LinkCreate, LinkType
from app.services import links as service


@pytest.fixture
def mock_db() -> AsyncMock:
    captured: list[Link] = []

    db = AsyncMock()
    db.get = AsyncMock(return_value=Port(id=1, switch_id=1, number=1))
    db.add = MagicMock(side_effect=lambda obj: captured.append(obj))
    db.commit = AsyncMock()

    async def _refresh(obj: Link) -> None:
        if obj.id is None:
            obj.id = 99

    db.refresh = AsyncMock(side_effect=_refresh)
    db._captured = captured  # type: ignore[attr-defined]
    return db


@pytest.mark.asyncio
async def test_link_swaps_reversed_endpoints(mock_db: AsyncMock) -> None:
    link = await service.create_link(
        mock_db, LinkCreate(port_a_id=10, port_b_id=3, link_type=LinkType.fiber)
    )
    assert link.port_a_id == 3
    assert link.port_b_id == 10


@pytest.mark.asyncio
async def test_link_preserves_already_canonical(mock_db: AsyncMock) -> None:
    link = await service.create_link(
        mock_db, LinkCreate(port_a_id=2, port_b_id=8, link_type=LinkType.copper)
    )
    assert link.port_a_id == 2
    assert link.port_b_id == 8
