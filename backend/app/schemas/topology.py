"""Topology graph response — Cytoscape.js element format.

Shape notes
-----------
Nodes carry a `parent` id, which is how Cytoscape draws compound (grouped)
nodes: a switch whose `parent` is `"room-3"` renders inside that room's box,
and the room's own `parent` puts that box inside its site. The frontend needs
no grouping logic of its own — the hierarchy is in the payload.

`id` is a prefixed string rather than the raw integer PK because a single
graph mixes four entity tables, and Cytoscape element ids share one
namespace. `entity_id` carries the un-prefixed PK for callers that need to
navigate to the entity's own page.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

NodeKind = Literal["site", "room", "switch", "device"]
EdgeKind = Literal["link", "attachment"]


class TopologyNodeData(BaseModel):
    # "site-<id>" | "room-<id>" | "sw-<id>" | "dev-<id>"
    id: str
    label: str
    kind: NodeKind
    entity_id: int
    # Compound parent: rooms sit in sites, switches and devices sit in rooms.
    # None for sites and for anything with no room assigned.
    parent: str | None = None

    # --- switch / device shared -------------------------------------------
    vendor: str | None = None
    model: str | None = None

    # --- switch only ------------------------------------------------------
    management_ip: str | None = None
    ports_total: int | None = None
    # Ports that are either an endpoint of a link or have a connected device.
    # Drives the utilisation meter on the node and in the inspector.
    ports_used: int | None = None

    # --- device only ------------------------------------------------------
    device_type: str | None = None

    # --- site / room only -------------------------------------------------
    # Direct children count, so a collapsed group can still say how much it
    # holds without the client counting nodes.
    child_count: int | None = None


class TopologyEdgeData(BaseModel):
    # "link-<id>" for a physical cable, "attach-<port_id>" for a device
    # plugged into a port.
    id: str
    kind: EdgeKind
    source: str
    target: str
    # Physical-cable fields — None on `attachment` edges.
    link_type: str | None = None
    speed_mbps: int | None = None
    # Port numbers at each end. On an attachment edge only `port_a` is set
    # (the switch-side port); the device end has no port of its own.
    port_a: int | None = None
    port_b: int | None = None
    port_a_label: str | None = None
    port_b_label: str | None = None


class TopologyNode(BaseModel):
    data: TopologyNodeData


class TopologyEdge(BaseModel):
    data: TopologyEdgeData


class TopologyStats(BaseModel):
    """Counts for the header strip — computed from the returned payload, so
    they always describe exactly what is on screen (including after
    truncation)."""

    sites: int = 0
    rooms: int = 0
    switches: int = 0
    devices: int = 0
    links: int = 0
    attachments: int = 0
    # Switches with no link and no attached device — the ones worth chasing.
    isolated_switches: int = 0
    # Switches and devices with no room assigned; they render outside any
    # group box, which is a data-quality signal rather than a layout one.
    unplaced_nodes: int = 0
    link_types: dict[str, int] = {}


class TopologyResponse(BaseModel):
    nodes: list[TopologyNode]
    edges: list[TopologyEdge]
    stats: TopologyStats = TopologyStats()
    # True when the inventory exceeded the render-side node/edge cap (see
    # `services/topology.py`) and the payload was cut down to the cap instead
    # of returning everything. Additive field, defaults to False — older
    # clients that don't know about it simply never see it.
    truncated: bool = False
