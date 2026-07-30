"""Tests for the topology graph builder.

`build_topology` issues its queries in a fixed order, so the mock DB below
feeds `db.execute` a matching sequence of results. `_mock_db` documents that
order in one place — if the query plan in `services/topology.py` changes,
this helper is the thing to update.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.core import Room, Site
from app.models.device import Device, DeviceType
from app.models.link import Link, LinkType
from app.models.port import Port
from app.models.switch import Switch
from app.services import topology as service


def _scalars_result(rows: list) -> MagicMock:
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=rows)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    return result


def _mock_db(
    switches: list[Switch],
    ports: list[Port],
    links: list[Link] | None = None,
    devices: list[Device] | None = None,
    rooms: list[Room] | None = None,
    sites: list[Site] | None = None,
    *,
    include_devices: bool = True,
) -> AsyncMock:
    """Feed `db.execute` the results in the order `build_topology` asks.

    The order is: switches → ports (only when there are switches) → devices
    (only when `include_devices`) → links (only when there are ports) → rooms
    and sites (only when some node references a room). Skipping the calls the
    builder won't make keeps a mis-ordered mock from passing by accident.
    """
    calls: list[MagicMock] = [_scalars_result(switches)]
    if switches:
        calls.append(_scalars_result(ports))
    if include_devices:
        calls.append(_scalars_result(devices or []))
    if ports:
        calls.append(_scalars_result(links or []))
    referenced_rooms = {
        s.room_id for s in switches if s.room_id is not None
    } | {d.room_id for d in (devices or []) if d.room_id is not None}
    if referenced_rooms:
        calls.append(_scalars_result(rooms or []))
        if rooms:
            calls.append(_scalars_result(sites or []))

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=calls)
    return db


def _switch(id: int, name: str, port_count: int = 24, room_id: int | None = None) -> Switch:
    return Switch(id=id, name=name, port_count=port_count, room_id=room_id)


def _port(
    id: int,
    switch_id: int,
    number: int,
    connected_device_id: int | None = None,
    label: str | None = None,
) -> Port:
    return Port(
        id=id,
        switch_id=switch_id,
        number=number,
        connected_device_id=connected_device_id,
        label=label,
    )


def _link(id: int, a: int, b: int, link_type: LinkType = LinkType.fiber) -> Link:
    return Link(id=id, port_a_id=a, port_b_id=b, link_type=link_type, speed_mbps=10000)


def _device(id: int, name: str, room_id: int | None = None) -> Device:
    return Device(id=id, name=name, type=DeviceType.server, room_id=room_id)


# --- Nodes ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_topology_returns_empty_graph() -> None:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalars_result([]))
    result = await service.build_topology(db)
    assert result.nodes == []
    assert result.edges == []
    assert result.stats.switches == 0


@pytest.mark.asyncio
async def test_topology_emits_one_node_per_switch() -> None:
    db = _mock_db(
        switches=[
            _switch(1, "SW-CORE", port_count=48),
            _switch(2, "SW-EDGE", port_count=24),
        ],
        ports=[_port(10, 1, 1), _port(20, 2, 1)],
    )
    result = await service.build_topology(db)
    node_ids = {n.data.id for n in result.nodes}
    assert node_ids == {"sw-1", "sw-2"}
    core = next(n for n in result.nodes if n.data.id == "sw-1")
    assert core.data.label == "SW-CORE"
    assert core.data.kind == "switch"
    assert core.data.entity_id == 1
    assert core.data.ports_total == 48
    # No link, no attached device → nothing is using a port.
    assert core.data.ports_used == 0


@pytest.mark.asyncio
async def test_switch_in_a_room_is_parented_to_room_and_site() -> None:
    """Grouping is the whole point of the compound payload: the switch names
    its room as parent, the room names its site, and both group nodes are
    emitted so Cytoscape can draw the boxes."""
    db = _mock_db(
        switches=[_switch(1, "SW-A", room_id=7)],
        ports=[_port(10, 1, 1)],
        rooms=[Room(id=7, site_id=3, code="MDF")],
        sites=[Site(id=3, code="PAR", name="Paris")],
    )
    result = await service.build_topology(db)

    by_id = {n.data.id: n.data for n in result.nodes}
    assert by_id["sw-1"].parent == "room-7"
    assert by_id["room-7"].parent == "site-3"
    assert by_id["site-3"].parent is None
    assert by_id["room-7"].kind == "room"
    assert by_id["site-3"].label == "PAR"
    # One switch in the room, one room in the site.
    assert by_id["room-7"].child_count == 1
    assert by_id["site-3"].child_count == 1


@pytest.mark.asyncio
async def test_switch_without_a_room_has_no_parent() -> None:
    """An unplaced switch renders outside every group box rather than being
    dropped — and it is counted so the UI can flag the data gap."""
    db = _mock_db(switches=[_switch(1, "SW-ORPHAN")], ports=[_port(10, 1, 1)])
    result = await service.build_topology(db)

    node = next(n.data for n in result.nodes if n.data.id == "sw-1")
    assert node.parent is None
    assert not [n for n in result.nodes if n.data.kind in ("room", "site")]
    assert result.stats.unplaced_nodes == 1


# --- Edges ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_topology_resolves_link_endpoints_to_switches() -> None:
    db = _mock_db(
        switches=[_switch(1, "A"), _switch(2, "B")],
        ports=[_port(10, 1, 48, label="uplink"), _port(20, 2, 24)],
        links=[_link(99, 10, 20)],
    )
    result = await service.build_topology(db)

    assert len(result.edges) == 1
    edge = result.edges[0].data
    assert edge.id == "link-99"
    assert edge.kind == "link"
    assert edge.source == "sw-1"
    assert edge.target == "sw-2"
    assert edge.port_a == 48
    assert edge.port_b == 24
    assert edge.port_a_label == "uplink"
    assert edge.link_type == "fiber"
    assert edge.speed_mbps == 10000


@pytest.mark.asyncio
async def test_connected_device_produces_an_attachment_edge() -> None:
    db = _mock_db(
        switches=[_switch(1, "SW-A")],
        ports=[_port(10, 1, 5, connected_device_id=42, label="srv-01")],
        devices=[_device(42, "srv-01")],
    )
    result = await service.build_topology(db)

    assert {n.data.id for n in result.nodes} == {"sw-1", "dev-42"}
    edge = next(e.data for e in result.edges if e.data.kind == "attachment")
    assert edge.id == "attach-10"
    assert edge.source == "sw-1"
    assert edge.target == "dev-42"
    # Only the switch side has a port; the device end has none.
    assert edge.port_a == 5
    assert edge.port_b is None
    assert edge.link_type is None
    assert result.stats.attachments == 1
    # The attached port counts as used even though there is no cable.
    assert next(n.data for n in result.nodes if n.data.id == "sw-1").ports_used == 1


@pytest.mark.asyncio
async def test_attachment_is_skipped_when_the_device_is_out_of_scope() -> None:
    """A port can reference a device the device query didn't return (filtered
    out, or over the device cap). Emitting the edge anyway would point at a
    node that isn't in the payload and break the render."""
    db = _mock_db(
        switches=[_switch(1, "SW-A")],
        ports=[_port(10, 1, 5, connected_device_id=42)],
        devices=[],
    )
    result = await service.build_topology(db)

    assert not [e for e in result.edges if e.data.kind == "attachment"]
    assert result.stats.attachments == 0


@pytest.mark.asyncio
async def test_include_devices_false_skips_the_device_query_entirely() -> None:
    db = _mock_db(
        switches=[_switch(1, "SW-A")],
        ports=[_port(10, 1, 5, connected_device_id=42)],
        include_devices=False,
    )
    result = await service.build_topology(db, include_devices=False)

    assert {n.data.id for n in result.nodes} == {"sw-1"}
    assert result.edges == []
    assert result.stats.devices == 0


@pytest.mark.asyncio
async def test_topology_drops_links_dangling_outside_filter() -> None:
    db = _mock_db(switches=[_switch(1, "A")], ports=[])
    result = await service.build_topology(db)
    assert len(result.nodes) == 1
    assert result.edges == []


# --- Stats ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_stats_describe_the_returned_payload() -> None:
    db = _mock_db(
        switches=[_switch(1, "A", room_id=7), _switch(2, "B", room_id=7), _switch(3, "LONE")],
        ports=[_port(10, 1, 1), _port(20, 2, 1), _port(30, 3, 1)],
        links=[_link(99, 10, 20)],
        rooms=[Room(id=7, site_id=3, code="MDF")],
        sites=[Site(id=3, code="PAR", name="Paris")],
    )
    result = await service.build_topology(db)

    stats = result.stats
    assert stats.switches == 3
    assert stats.links == 1
    assert stats.sites == 1
    assert stats.rooms == 1
    # sw-3 has a port but neither a link nor a device on it.
    assert stats.isolated_switches == 1
    assert stats.unplaced_nodes == 1
    assert stats.link_types == {"fiber": 1}


# --- Caps -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_topology_default_response_is_not_truncated() -> None:
    """`truncated` must default to False on the ordinary, under-the-cap path —
    it's an additive field and must stay invisible unless it fires."""
    db = _mock_db(
        switches=[_switch(1, "A"), _switch(2, "B")],
        ports=[_port(10, 1, 1), _port(20, 2, 1)],
        links=[_link(99, 10, 20)],
    )
    result = await service.build_topology(db)
    assert result.truncated is False


@pytest.mark.asyncio
async def test_topology_truncates_when_switches_exceed_node_cap() -> None:
    """More than `_MAX_NODES` switches: the query itself is capped at
    `_MAX_NODES + 1` (so we can tell "over the cap" from "exactly at it"
    without loading everything), the response is cut down to the cap, and
    `truncated` is set so the caller knows the graph isn't complete."""
    over_cap = service._MAX_NODES + 1
    switches = [_switch(i, f"SW-{i}") for i in range(1, over_cap + 1)]
    db = _mock_db(switches=switches, ports=[])

    result = await service.build_topology(db)
    assert len([n for n in result.nodes if n.data.kind == "switch"]) == service._MAX_NODES
    assert result.truncated is True


@pytest.mark.asyncio
async def test_topology_truncates_when_devices_exceed_device_cap() -> None:
    """Devices have their own cap: they are leaves and can outnumber switches
    by an order of magnitude, so they must not push switches out of the
    payload."""
    over_cap = service._MAX_DEVICE_NODES + 1
    devices = [_device(i, f"dev-{i}") for i in range(1, over_cap + 1)]
    db = _mock_db(switches=[_switch(1, "A")], ports=[_port(10, 1, 1)], devices=devices)

    result = await service.build_topology(db)
    assert (
        len([n for n in result.nodes if n.data.kind == "device"])
        == service._MAX_DEVICE_NODES
    )
    assert result.truncated is True


@pytest.mark.asyncio
async def test_topology_truncates_when_links_exceed_edge_cap() -> None:
    """A switch set under the node cap can still produce more than
    `_MAX_EDGES` links (a dense mesh) — that must be capped independently."""
    over_cap = service._MAX_EDGES + 1
    links = [_link(i, 10, 20) for i in range(1, over_cap + 1)]
    db = _mock_db(
        switches=[_switch(1, "A"), _switch(2, "B")],
        ports=[_port(10, 1, 1), _port(20, 2, 1)],
        links=links,
    )

    result = await service.build_topology(db)
    assert len([e for e in result.edges if e.data.kind == "link"]) == service._MAX_EDGES
    assert result.truncated is True
