"""Verify that creating a switch attaches exactly N ports in `access`/`up`."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.port import Port, PortAdminStatus, PortMode
from app.models.switch import Switch
from app.schemas.switch import SwitchCreate
from app.services import switches as service


@pytest.mark.asyncio
async def test_create_switch_attaches_n_ports() -> None:
    captured: list[Switch] = []

    db = AsyncMock()
    db.add = MagicMock(side_effect=lambda obj: captured.append(obj))
    db.commit = AsyncMock()

    async def _refresh(obj: Switch) -> None:
        if obj.id is None:
            obj.id = 1

    db.refresh = AsyncMock(side_effect=_refresh)

    payload = SwitchCreate(name="SW-A", port_count=24)
    switch = await service.create_switch(db, payload)

    assert captured == [switch]
    assert len(switch.ports) == 24
    assert [p.number for p in switch.ports] == list(range(1, 25))
    assert all(isinstance(p, Port) for p in switch.ports)
    assert all(p.mode == PortMode.access for p in switch.ports)
    assert all(p.admin_status == PortAdminStatus.up for p in switch.ports)


@pytest.mark.asyncio
async def test_create_switch_with_48_ports() -> None:
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    switch = await service.create_switch(db, SwitchCreate(name="SW-B", port_count=48))

    assert len(switch.ports) == 48
    assert switch.ports[-1].number == 48
