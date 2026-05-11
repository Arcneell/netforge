"""Topology graph response — Cytoscape.js format."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class TopologyNodeData(BaseModel):
    id: str  # "sw-<switch_id>"
    label: str
    type: Literal["switch"] = "switch"
    vendor: str | None = None
    model: str | None = None
    management_ip: str | None = None
    room_id: int | None = None
    ports_total: int


class TopologyEdgeData(BaseModel):
    id: str  # "link-<link_id>"
    source: str  # "sw-<switch_id>"
    target: str  # "sw-<switch_id>"
    link_type: str
    speed_mbps: int | None = None
    port_a: int  # port number on source
    port_b: int  # port number on target


class TopologyNode(BaseModel):
    data: TopologyNodeData


class TopologyEdge(BaseModel):
    data: TopologyEdgeData


class TopologyResponse(BaseModel):
    nodes: list[TopologyNode]
    edges: list[TopologyEdge]
