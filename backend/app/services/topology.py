"""Topology graph builder.

What the graph contains
----------------------
Four node kinds in one payload: sites and rooms as compound *group* nodes,
switches and devices as leaf nodes inside them. Two edge kinds: `link` for a
physical cable between two switch ports, and `attachment` for a device
plugged into a switch port (`ports.connected_device_id`).

Grouping is what makes a network graph readable — a flat mesh of 40 switches
tells you nothing, the same 40 switches boxed by site and room tells you the
shape of the estate. Cytoscape draws that from the `parent` field, so the
hierarchy is computed here rather than reassembled in the browser.

Group nodes are only emitted for rooms that actually hold something, and for
sites that hold such a room. An empty site would otherwise render as a large
labelled void.

Query plan
----------
  1. Switches (optionally filtered by site / room / VLAN).
  2. Devices in the same rooms, when `include_devices` is on.
  3. Ports of those switches — needed for link endpoints, port labels, and
     the used-port count.
  4. Links where BOTH endpoints belong to the visible switches.
  5. Rooms + sites for the ones actually referenced.

For a typical network (< 50 switches, < 500 links) this is sub-50 ms; the
docs/09 perf notes apply. Above that, the switch and link queries are capped
at the DB level (`_MAX_NODES` / `_MAX_EDGES`) instead of loading the whole
graph into memory just to truncate it in Python. `TopologyResponse.truncated`
tells the caller the payload was cut down.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import Room, Site
from app.models.device import Device
from app.models.link import Link
from app.models.port import Port, PortVlan
from app.models.switch import Switch
from app.schemas.topology import (
    TopologyEdge,
    TopologyEdgeData,
    TopologyNode,
    TopologyNodeData,
    TopologyResponse,
    TopologyStats,
)

logger = logging.getLogger("netforge.topology")

# Render-side caps. 10x the perf-notes baseline (~50 switches / ~500 links) —
# generous enough that no real deployment should hit it in normal use, tight
# enough to keep the response bounded and the cytoscape.js render inside
# territory it has actually been exercised at. Devices share the node cap:
# they are leaves and can outnumber switches by an order of magnitude, so
# they get their own slice rather than pushing switches out of the payload.
_MAX_NODES = 500
_MAX_DEVICE_NODES = 500
_MAX_EDGES = 2000


async def build_topology(
    db: AsyncSession,
    site_id: int | None = None,
    room_id: int | None = None,
    vlan_id: int | None = None,
    include_devices: bool = True,
) -> TopologyResponse:
    """Build the graph for the given scope.

    `vlan_id` is a *switch* filter, not an edge filter: it keeps switches that
    carry the VLAN on at least one port (native or tagged), then draws every
    link between them. Filtering the edges too would hide the cable that
    actually carries the VLAN between two of those switches, which is the one
    thing the operator opened the view to see.
    """
    truncated = False

    # ---- 1. Switches -----------------------------------------------------
    # Ordered + capped at `_MAX_NODES + 1` so "exactly the cap" and "more
    # than the cap" are distinguishable without loading everything.
    switch_q = select(Switch).order_by(Switch.id).limit(_MAX_NODES + 1)
    if site_id is not None or room_id is not None:
        switch_q = switch_q.join(Room, Switch.room_id == Room.id)
        if site_id is not None:
            switch_q = switch_q.where(Room.site_id == site_id)
        if room_id is not None:
            switch_q = switch_q.where(Room.id == room_id)
    if vlan_id is not None:
        # A switch is "on" a VLAN if any of its ports carries it as the
        # native VLAN or has it in its tagged set.
        native_match = select(Port.switch_id).where(Port.native_vlan_id == vlan_id)
        tagged_match = (
            select(Port.switch_id)
            .join(PortVlan, PortVlan.port_id == Port.id)
            .where(PortVlan.vlan_id == vlan_id)
        )
        switch_q = switch_q.where(
            Switch.id.in_(native_match.union(tagged_match).subquery().select())
        )

    switches = list((await db.execute(switch_q)).scalars().all())
    if len(switches) > _MAX_NODES:
        truncated = True
        switches = switches[:_MAX_NODES]
        logger.warning(
            "topology.truncated site_id=%s room_id=%s reason=nodes_over_cap max=%d",
            site_id,
            room_id,
            _MAX_NODES,
        )

    switch_ids = {sw.id for sw in switches}

    # ---- 2. Ports of those switches --------------------------------------
    # Bounded by the switch cap. Needed three times over: link endpoints,
    # port labels in the inspector, and the used-port count per switch.
    ports: list[Port] = []
    if switch_ids:
        ports = list(
            (
                await db.execute(select(Port).where(Port.switch_id.in_(switch_ids)))
            )
            .scalars()
            .all()
        )
    port_by_id = {p.id: p for p in ports}

    # ---- 3. Devices ------------------------------------------------------
    # Two independent reasons a device belongs in the graph: it is plugged
    # into a visible switch (so it has an edge), or it merely sits in one of
    # the rooms in scope (so it is inventory the operator can see is there,
    # unconnected). Both are wanted; the second is how "this room has a
    # server nobody cabled" becomes visible at all.
    devices: list[Device] = []
    if include_devices:
        attached_device_ids = {
            p.connected_device_id for p in ports if p.connected_device_id is not None
        }
        device_q = select(Device).order_by(Device.id).limit(_MAX_DEVICE_NODES + 1)
        room_ids_in_scope = {sw.room_id for sw in switches if sw.room_id is not None}
        if site_id is not None or room_id is not None:
            # Scoped view: only devices in the rooms the scope covers, plus
            # any device attached to a visible switch even if it is filed
            # under a different room.
            scope_rooms = select(Room.id)
            if site_id is not None:
                scope_rooms = scope_rooms.where(Room.site_id == site_id)
            if room_id is not None:
                scope_rooms = scope_rooms.where(Room.id == room_id)
            criteria = [Device.room_id.in_(scope_rooms)]
            if attached_device_ids:
                criteria.append(Device.id.in_(attached_device_ids))
            device_q = device_q.where(_any_of(criteria))
        elif room_ids_in_scope or attached_device_ids:
            # Unscoped: every device, which is what the caller asked for.
            pass
        devices = list((await db.execute(device_q)).scalars().all())
        if len(devices) > _MAX_DEVICE_NODES:
            truncated = True
            devices = devices[:_MAX_DEVICE_NODES]
            logger.warning(
                "topology.truncated reason=devices_over_cap max=%d",
                _MAX_DEVICE_NODES,
            )

    device_ids = {d.id for d in devices}

    # ---- 4. Links --------------------------------------------------------
    links: list[Link] = []
    if port_by_id:
        port_ids = set(port_by_id)
        links = list(
            (
                await db.execute(
                    select(Link)
                    .where(
                        Link.port_a_id.in_(port_ids),
                        Link.port_b_id.in_(port_ids),
                    )
                    .order_by(Link.id)
                    .limit(_MAX_EDGES + 1)
                )
            )
            .scalars()
            .all()
        )
        if len(links) > _MAX_EDGES:
            truncated = True
            links = links[:_MAX_EDGES]
            logger.warning(
                "topology.truncated reason=edges_over_cap max=%d", _MAX_EDGES
            )

    # ---- 5. Rooms and sites actually referenced --------------------------
    referenced_room_ids = {
        r
        for r in (
            *(sw.room_id for sw in switches),
            *(d.room_id for d in devices),
        )
        if r is not None
    }
    rooms: list[Room] = []
    sites: list[Site] = []
    if referenced_room_ids:
        rooms = list(
            (
                await db.execute(
                    select(Room).where(Room.id.in_(referenced_room_ids))
                )
            )
            .scalars()
            .all()
        )
        referenced_site_ids = {r.site_id for r in rooms}
        if referenced_site_ids:
            sites = list(
                (
                    await db.execute(
                        select(Site).where(Site.id.in_(referenced_site_ids))
                    )
                )
                .scalars()
                .all()
            )

    # ---- Assemble --------------------------------------------------------
    nodes: list[TopologyNode] = []
    edges: list[TopologyEdge] = []

    # Used-port count per switch: a port counts as used if it terminates a
    # link or has a device plugged in.
    linked_port_ids = {p for link in links for p in (link.port_a_id, link.port_b_id)}
    used_ports_per_switch: Counter[int] = Counter()
    for port in ports:
        if port.id in linked_port_ids or port.connected_device_id is not None:
            used_ports_per_switch[port.switch_id] += 1

    children_per_room: Counter[int] = Counter()
    for sw in switches:
        if sw.room_id is not None:
            children_per_room[sw.room_id] += 1
    for dev in devices:
        if dev.room_id is not None:
            children_per_room[dev.room_id] += 1

    rooms_per_site: Counter[int] = Counter(r.site_id for r in rooms)

    for site in sites:
        nodes.append(
            TopologyNode(
                data=TopologyNodeData(
                    id=f"site-{site.id}",
                    label=site.code,
                    kind="site",
                    entity_id=site.id,
                    child_count=rooms_per_site.get(site.id, 0),
                )
            )
        )
    for room in rooms:
        nodes.append(
            TopologyNode(
                data=TopologyNodeData(
                    id=f"room-{room.id}",
                    label=room.code,
                    kind="room",
                    entity_id=room.id,
                    parent=f"site-{room.site_id}",
                    child_count=children_per_room.get(room.id, 0),
                )
            )
        )
    for sw in switches:
        nodes.append(
            TopologyNode(
                data=TopologyNodeData(
                    id=f"sw-{sw.id}",
                    label=sw.name,
                    kind="switch",
                    entity_id=sw.id,
                    parent=None if sw.room_id is None else f"room-{sw.room_id}",
                    vendor=sw.vendor,
                    model=sw.model,
                    management_ip=(
                        None if sw.management_ip is None else str(sw.management_ip)
                    ),
                    ports_total=sw.port_count,
                    ports_used=used_ports_per_switch.get(sw.id, 0),
                )
            )
        )
    for dev in devices:
        nodes.append(
            TopologyNode(
                data=TopologyNodeData(
                    id=f"dev-{dev.id}",
                    label=dev.name,
                    kind="device",
                    entity_id=dev.id,
                    parent=None if dev.room_id is None else f"room-{dev.room_id}",
                    vendor=dev.vendor,
                    model=dev.model,
                    device_type=_enum_value(dev.type),
                )
            )
        )

    for link in links:
        port_a = port_by_id[link.port_a_id]
        port_b = port_by_id[link.port_b_id]
        edges.append(
            TopologyEdge(
                data=TopologyEdgeData(
                    id=f"link-{link.id}",
                    kind="link",
                    source=f"sw-{port_a.switch_id}",
                    target=f"sw-{port_b.switch_id}",
                    link_type=_enum_value(link.link_type),
                    speed_mbps=link.speed_mbps,
                    port_a=port_a.number,
                    port_b=port_b.number,
                    port_a_label=port_a.label,
                    port_b_label=port_b.label,
                )
            )
        )

    attachments = 0
    for port in ports:
        if port.connected_device_id is None or port.connected_device_id not in device_ids:
            continue
        attachments += 1
        edges.append(
            TopologyEdge(
                data=TopologyEdgeData(
                    id=f"attach-{port.id}",
                    kind="attachment",
                    source=f"sw-{port.switch_id}",
                    target=f"dev-{port.connected_device_id}",
                    port_a=port.number,
                    port_a_label=port.label,
                )
            )
        )

    connected_switch_ids = {
        port.switch_id
        for port in ports
        if port.id in linked_port_ids
        or (port.connected_device_id is not None and port.connected_device_id in device_ids)
    }
    stats = TopologyStats(
        sites=len(sites),
        rooms=len(rooms),
        switches=len(switches),
        devices=len(devices),
        links=len(links),
        attachments=attachments,
        isolated_switches=sum(1 for sw in switches if sw.id not in connected_switch_ids),
        unplaced_nodes=sum(1 for sw in switches if sw.room_id is None)
        + sum(1 for d in devices if d.room_id is None),
        link_types=dict(Counter(_enum_value(link.link_type) for link in links)),
    )

    return TopologyResponse(
        nodes=nodes, edges=edges, stats=stats, truncated=truncated
    )


def _enum_value(value: object) -> str:
    """Enum columns come back as the Enum on the ORM path and as a bare string
    on some raw/cached paths — normalise both to the wire value."""
    return getattr(value, "value", None) or str(value)


def _any_of(criteria: list[Any]) -> Any:
    """OR the criteria together, or return the single one unchanged.

    `or_()` with one argument warns in SQLAlchemy 2.x, and the device scope
    above legitimately has either one clause or two.
    """
    if len(criteria) == 1:
        return criteria[0]
    return or_(*criteria)
