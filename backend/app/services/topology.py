"""Topology graph builder.

Three queries:
  1. Switches (optionally filtered by site through their room).
  2. Ports of those switches (we only need id → (switch_id, number)).
  3. Links where BOTH endpoints belong to those switches.

For a typical network (< 50 switches, < 500 links) this is sub-50 ms; the
docs/09 perf notes apply.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import Room
from app.models.link import Link
from app.models.port import Port
from app.models.switch import Switch
from app.schemas.topology import (
    TopologyEdge,
    TopologyEdgeData,
    TopologyNode,
    TopologyNodeData,
    TopologyResponse,
)


async def build_topology(
    db: AsyncSession, site_id: int | None = None
) -> TopologyResponse:
    # 1. Switches
    switch_q = select(Switch)
    if site_id is not None:
        switch_q = switch_q.join(Room, Switch.room_id == Room.id).where(
            Room.site_id == site_id
        )
    switches = (await db.execute(switch_q)).scalars().all()

    nodes: list[TopologyNode] = [
        TopologyNode(
            data=TopologyNodeData(
                id=f"sw-{sw.id}",
                label=sw.name,
                vendor=sw.vendor,
                model=sw.model,
                management_ip=None if sw.management_ip is None else str(sw.management_ip),
                room_id=sw.room_id,
                ports_total=sw.port_count,
            )
        )
        for sw in switches
    ]

    if not switches:
        return TopologyResponse(nodes=nodes, edges=[])

    switch_ids = {sw.id for sw in switches}

    # 2. Ports of those switches
    port_rows = (
        await db.execute(select(Port).where(Port.switch_id.in_(switch_ids)))
    ).scalars().all()
    port_info: dict[int, tuple[int, int]] = {
        p.id: (p.switch_id, p.number) for p in port_rows
    }

    if not port_info:
        return TopologyResponse(nodes=nodes, edges=[])

    port_ids = set(port_info)

    # 3. Links with both endpoints inside the visible set
    link_rows = (
        await db.execute(
            select(Link).where(
                Link.port_a_id.in_(port_ids),
                Link.port_b_id.in_(port_ids),
            )
        )
    ).scalars().all()

    edges: list[TopologyEdge] = []
    for link in link_rows:
        source_switch, source_port = port_info[link.port_a_id]
        target_switch, target_port = port_info[link.port_b_id]
        edges.append(
            TopologyEdge(
                data=TopologyEdgeData(
                    id=f"link-{link.id}",
                    source=f"sw-{source_switch}",
                    target=f"sw-{target_switch}",
                    link_type=link.link_type.value
                    if hasattr(link.link_type, "value")
                    else str(link.link_type),
                    speed_mbps=link.speed_mbps,
                    port_a=source_port,
                    port_b=target_port,
                )
            )
        )

    return TopologyResponse(nodes=nodes, edges=edges)
