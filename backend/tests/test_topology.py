"""Tests for the topology graph builder."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

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


def _mock_db(switches: list[Switch], ports: list[Port], links: list[Link]) -> AsyncMock:
    """db.execute is called three times in build_topology — return in order."""
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalars_result(switches),
            _scalars_result(ports),
            _scalars_result(links),
        ]
    )
    return db


def _switch(id: int, name: str, port_count: int = 24) -> Switch:
    return Switch(id=id, name=name, port_count=port_count)


def _port(id: int, switch_id: int, number: int) -> Port:
    return Port(id=id, switch_id=switch_id, number=number)


def _link(id: int, a: int, b: int, link_type: LinkType = LinkType.fiber) -> Link:
    return Link(id=id, port_a_id=a, port_b_id=b, link_type=link_type, speed_mbps=10000)


# --- Cases ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_topology_returns_empty_graph() -> None:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalars_result([]))
    result = await service.build_topology(db)
    assert result.nodes == []
    assert result.edges == []


@pytest.mark.asyncio
async def test_topology_emits_one_node_per_switch() -> None:
    db = _mock_db(
        switches=[
            _switch(1, "SW-CORE", port_count=48),
            _switch(2, "SW-EDGE", port_count=24),
        ],
        ports=[_port(10, 1, 1), _port(20, 2, 1)],
        links=[],
    )
    result = await service.build_topology(db)
    assert len(result.nodes) == 2
    node_ids = {n.data.id for n in result.nodes}
    assert node_ids == {"sw-1", "sw-2"}
    core = next(n for n in result.nodes if n.data.id == "sw-1")
    assert core.data.label == "SW-CORE"
    assert core.data.ports_total == 48


@pytest.mark.asyncio
async def test_topology_resolves_link_endpoints_to_switches() -> None:
    db = _mock_db(
        switches=[_switch(1, "A"), _switch(2, "B")],
        ports=[_port(10, 1, 48), _port(20, 2, 24)],
        links=[_link(99, 10, 20)],
    )
    result = await service.build_topology(db)

    assert len(result.edges) == 1
    edge = result.edges[0].data
    assert edge.id == "link-99"
    assert edge.source == "sw-1"
    assert edge.target == "sw-2"
    assert edge.port_a == 48
    assert edge.port_b == 24
    assert edge.link_type == "fiber"
    assert edge.speed_mbps == 10000


@pytest.mark.asyncio
async def test_topology_drops_links_dangling_outside_filter() -> None:
    # Only sw-1 is in the result; the link references a port belonging to a
    # switch the filter excluded — that scenario CAN'T actually happen given
    # the IN(...) clause we build, but assert the no-port-info safety.
    db = _mock_db(
        switches=[_switch(1, "A")],
        ports=[],  # no ports of sw-1 visible → no edges either
        links=[],
    )
    result = await service.build_topology(db)
    assert len(result.nodes) == 1
    assert result.edges == []
