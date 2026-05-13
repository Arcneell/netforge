"""Tests for the global search service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.core import Room, Site
from app.models.device import Device, DeviceType
from app.models.ip import Ip, IpStatus
from app.models.port import Port
from app.models.subnet import Subnet
from app.models.switch import Switch
from app.models.vlan import Vlan
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
    sites: list[Site] | None = None,
    room_join_rows: list[tuple[Room, str]] | None = None,
    vlans: list[Vlan] | None = None,
    subnet_join_rows: list[tuple[Subnet, str | None]] | None = None,
) -> AsyncMock:
    """search() does 8 db.execute calls in order:
    ips, devices, switches, ports, sites, rooms, vlans, subnets."""
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalars(ips or []),
            _scalars(devices or []),
            _scalars(switches or []),
            _rows(port_join_rows or []),
            _scalars(sites or []),
            _rows(room_join_rows or []),
            _scalars(vlans or []),
            _rows(subnet_join_rows or []),
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
        sites=[Site(id=5, code="x", name="X-site")],
        room_join_rows=[(Room(id=6, site_id=5, code="x"), "PAR")],
        vlans=[Vlan(id=7, vlan_id=10, name="x")],
        subnet_join_rows=[(Subnet(id=8, site_id=5, cidr="10.0.30.0/24"), "PAR")],
    )
    results = await service.search(db, "x")
    types = {r.type for r in results}
    assert types == {"ip", "device", "switch", "port", "site", "room", "vlan", "subnet"}


# --- New entity types ----------------------------------------------------- #


@pytest.mark.asyncio
async def test_search_site_match_by_code() -> None:
    db = _mock_db(sites=[Site(id=12, code="PAR", name="Paris HQ")])
    results = await service.search(db, "PAR")
    assert len(results) == 1
    assert results[0].type == "site"
    assert results[0].label == "PAR"
    assert results[0].context == "Paris HQ"


@pytest.mark.asyncio
async def test_search_room_match_uses_site_qualified_label() -> None:
    """A room's code might collide across sites — the label disambiguates."""
    db = _mock_db(
        room_join_rows=[
            (Room(id=99, site_id=12, code="SALLE-SRV-01", description="Rack A"), "PAR"),
        ]
    )
    results = await service.search(db, "SRV")
    assert len(results) == 1
    assert results[0].type == "room"
    assert results[0].label == "PAR / SALLE-SRV-01"
    assert results[0].context == "Rack A"


@pytest.mark.asyncio
async def test_search_vlan_match_by_numeric_id() -> None:
    """Pattern `10` should match VLAN 10's vlan_id even though the field
    is an int — the service casts to text so ILIKE works."""
    db = _mock_db(vlans=[Vlan(id=3, vlan_id=10, name="VLAN-SRV", description="Servers")])
    results = await service.search(db, "10")
    assert len(results) == 1
    assert results[0].type == "vlan"
    # `id` is the DB primary key (so the frontend router can navigate); the
    # public 802.1Q id is encoded in the label.
    assert results[0].id == 3
    assert "10" in results[0].label
    assert "VLAN-SRV" in results[0].label


@pytest.mark.asyncio
async def test_search_subnet_match_includes_site_in_context() -> None:
    db = _mock_db(
        subnet_join_rows=[
            (
                Subnet(id=44, site_id=12, cidr="10.0.30.0/24", description="Voip floor 1"),
                "PAR",
            ),
        ]
    )
    results = await service.search(db, "10.0.30")
    assert len(results) == 1
    assert results[0].type == "subnet"
    assert results[0].label == "10.0.30.0/24"
    # Site code + description bundled in the context line for scannability.
    assert results[0].context is not None
    assert "PAR" in results[0].context
    assert "Voip" in results[0].context
