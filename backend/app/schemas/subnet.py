"""Subnets — IPv4 CIDR blocks."""

from __future__ import annotations

from datetime import datetime
from ipaddress import IPv4Address, IPv4Network

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _to_str_v4_network(value: str | IPv4Network) -> str:
    """Parse the value as an IPv4 network and re-serialize in canonical form."""
    network = value if isinstance(value, IPv4Network) else IPv4Network(value, strict=False)
    return str(network)


def _to_str_v4_address(value: str | IPv4Address | None) -> str | None:
    if value is None:
        return None
    return str(value if isinstance(value, IPv4Address) else IPv4Address(value))


class SubnetBase(BaseModel):
    cidr: str = Field(description="IPv4 CIDR, e.g. 10.0.30.0/24")
    gateway: str | None = None
    vlan_id: int | None = Field(default=None, gt=0)
    site_id: int = Field(gt=0)
    vrf_id: int | None = Field(default=None, gt=0)
    parent_subnet_id: int | None = Field(default=None, gt=0)
    description: str | None = None
    dhcp_enabled: bool = False
    dhcp_range_start: str | None = None
    dhcp_range_end: str | None = None

    @field_validator("cidr", mode="before")
    @classmethod
    def _validate_cidr(cls, v: object) -> str:
        return _to_str_v4_network(v)  # type: ignore[arg-type]

    @field_validator("gateway", "dhcp_range_start", "dhcp_range_end", mode="before")
    @classmethod
    def _validate_address(cls, v: object) -> str | None:
        return _to_str_v4_address(v)  # type: ignore[arg-type]


class SubnetCreate(SubnetBase):
    pass


class SubnetUpdate(BaseModel):
    cidr: str | None = None
    gateway: str | None = None
    vlan_id: int | None = Field(default=None, gt=0)
    site_id: int | None = Field(default=None, gt=0)
    vrf_id: int | None = Field(default=None, gt=0)
    parent_subnet_id: int | None = Field(default=None, gt=0)
    description: str | None = None
    dhcp_enabled: bool | None = None
    dhcp_range_start: str | None = None
    dhcp_range_end: str | None = None

    @field_validator("cidr", mode="before")
    @classmethod
    def _validate_cidr(cls, v: object) -> str | None:
        if v is None:
            return None
        return _to_str_v4_network(v)  # type: ignore[arg-type]

    @field_validator("gateway", "dhcp_range_start", "dhcp_range_end", mode="before")
    @classmethod
    def _validate_address(cls, v: object) -> str | None:
        return _to_str_v4_address(v)  # type: ignore[arg-type]


class SubnetRead(SubnetBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime
    # Populated by the list endpoint so the UI can render a fill bar
    # without going back to the utilisation route per row. Both default
    # to 0 so single-subnet reads (which don't pre-compute them) still
    # validate cleanly.
    usable: int = 0
    used: int = 0


class SubnetTreeNode(BaseModel):
    """One node of the subnet hierarchy tree.

    `children` is depth-first; siblings ordered by CIDR ascending. Root
    nodes are the subnets that have no parent (or whose parent rests in a
    different VRF — orphaned children float back to the top of their VRF).

    `vlan_id`, `gateway`, `usable` and `used` are populated by the service
    so the UI tree row can render the VLAN badge, gateway and fill-rate
    bar without a follow-up fetch per node.
    """

    model_config = ConfigDict(from_attributes=True)
    id: int
    cidr: str
    site_id: int
    vrf_id: int | None
    vlan_id: int | None = None
    parent_subnet_id: int | None
    description: str | None
    gateway: str | None = None
    usable: int = 0
    used: int = 0
    children: list[SubnetTreeNode] = []


SubnetTreeNode.model_rebuild()


# --- Utility responses (phase 4) ---------------------------------------------


class SubnetIpEntry(BaseModel):
    """One row in the GET /api/subnets/{id}/ips response.

    `status` may be one of the stored statuses (`reserved`, `assigned`, `dhcp`)
    OR the synthetic `"free"` for addresses that have no row in `ips`.
    """

    address: str
    status: str
    hostname: str | None = None
    mac: str | None = None
    device_id: int | None = None
    description: str | None = None


class SubnetIpsResponse(BaseModel):
    subnet: SubnetRead
    ips: list[SubnetIpEntry]


class NextFreeIpResponse(BaseModel):
    address: str


class SubnetUtilization(BaseModel):
    """Snapshot of how full a subnet is.

    `usable` is the number of host-usable addresses (excludes network +
    broadcast except on /31 and /32, per RFC 3021). The status counters
    are per-IP-record counts attached to the subnet. `free = usable -
    sum(status_*)` and matches the synthesised "free" rows from the
    address-space scan endpoint.
    """

    model_config = ConfigDict(from_attributes=True)
    subnet_id: int
    cidr: str
    usable: int
    free: int
    used_pct: int
    status_assigned: int
    status_reserved: int
    status_dhcp: int
