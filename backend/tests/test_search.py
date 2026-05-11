"""Tests for the global search service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.device import Device, DeviceType
from app.models.ip import Ip, IpStatus
from app.models.port import Port
from app.models.switch import Switch
from app.services import search as service


def _scalars(rows: list) -> MagicMock:
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=rows)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    return result


def _rows(rows: list) -> MagicMock:
    """Mimic db.execute(...).all() for tuple-returning SELECTs."""
    result = MagicMock()
    result.all = MagicMock(return_value=rows)
    return result


def _mock_db(
    ips: list[Ip] | None = None,
    devices: list[Device] | None = None,
    switches: list[Switch] | None = None,
    port_join_rows: list[tuple[Port, Switch]] | None = None,
) -> AsyncMock:
    """search() does 4 db.execute calls in order: ips, devices, switches, ports."""
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalars(ips or []),
            _scalars(devices or []),
            _scalars(switches or []),
            _rows(port_join_rows or []),
        ]
    )
    return db


# --- Cases ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_returns_empty_when_no_matches() -> None:
    db = _mock_db()
    results = await service.search(db, "no-match")
    assert results == []


@pytest.mark.asyncio
async def test_search_ip_match_includes_hostname_in_context() -> None:
    db = _mock_db(
        ips=[
            Ip(
                id=42, subnet_id=1, address="10.0.30.5",
                status=IpStatus.assigned, hostname="srv-ad-01",
            )
        ]
    )
    results = await service.search(db, "srv-ad")
    assert len(results) == 1
    r = results[0]
    assert r.type == "ip"
    assert r.id == 42
    assert r.label == "10.0.30.5"
    assert "srv-ad-01" in (r.context or "")


@pytest.mark.asyncio
async def test_search_device_match() -> None:
    db = _mock_db(
        devices=[
            Device(
                id=7, name="srv-ad-01", type=DeviceType.server,
                vendor="HP", model="ProLiant",
            )
        ]
    )
    results = await service.search(db, "ad-01")
    assert [(r.type, r.id, r.label) for r in results] == [
        ("device", 7, "srv-ad-01")
    ]
    assert "HP" in (results[0].context or "")


@pytest.mark.asyncio
async def test_search_switch_match() -> None:
    db = _mock_db(
        switches=[Switch(id=3, name="SW-SRV-01", port_count=48, vendor="Aruba")]
    )
    results = await service.search(db, "SW-SRV")
    assert results[0].type == "switch"
    assert results[0].label == "SW-SRV-01"


@pytest.mark.asyncio
async def test_search_port_match_renders_switch_qualified_label() -> None:
    sw = Switch(id=3, name="SW-SRV-01", port_count=48)
    port = Port(id=712, switch_id=3, number=14, label="Bureau compta 3")
    db = _mock_db(port_join_rows=[(port, sw)])
    results = await service.search(db, "compta")
    assert len(results) == 1
    assert results[0].type == "port"
    assert results[0].id == 712
    assert results[0].label == "SW-SRV-01 / port 14"
    assert results[0].context == "Bureau compta 3"


@pytest.mark.asyncio
async def test_search_returns_all_categories_when_multiple_match() -> None:
    db = _mock_db(
        ips=[Ip(id=1, subnet_id=1, address="10.0.30.5", status=IpStatus.assigned, hostname="x")],
        devices=[Device(id=2, name="x", type=DeviceType.server)],
        switches=[Switch(id=3, name="x", port_count=24)],
        port_join_rows=[(Port(id=4, switch_id=3, number=1, label="x"), Switch(id=3, name="SW-A", port_count=24))],
    )
    results = await service.search(db, "x")
    types = {r.type for r in results}
    assert types == {"ip", "device", "switch", "port"}
