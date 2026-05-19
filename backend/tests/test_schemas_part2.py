"""Schema validation tests for the part-2 entities (devices, switches, ports, links)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.device import DeviceCreate, DeviceType
from app.schemas.link import LinkCreate, LinkType
from app.schemas.port import PortMode, PortUpdate
from app.schemas.switch import SwitchCreate

# --- Devices ---


def test_device_create_requires_known_type() -> None:
    DeviceCreate(name="srv-01", type=DeviceType.server)
    with pytest.raises(ValidationError):
        DeviceCreate(name="x", type="mainframe")  # type: ignore[arg-type]


# --- Switches ---


def test_switch_create_rejects_zero_ports() -> None:
    with pytest.raises(ValidationError):
        SwitchCreate(name="SW-X", port_count=0)


def test_switch_create_rejects_huge_port_count() -> None:
    with pytest.raises(ValidationError):
        SwitchCreate(name="SW-X", port_count=10000)


def test_switch_management_ip_validates() -> None:
    payload = SwitchCreate(name="SW-X", port_count=24, management_ip="10.0.0.1")
    assert payload.management_ip == "10.0.0.1"
    with pytest.raises(ValidationError):
        SwitchCreate(name="SW-X", port_count=24, management_ip="bad")


# --- Ports ---


def test_port_update_accepts_partial_payload() -> None:
    PortUpdate(label="bureau-1")
    PortUpdate(mode=PortMode.trunk, native_vlan_id=10)
    # Empty patch is allowed (idempotent PUT with no changes).
    assert PortUpdate().model_dump(exclude_unset=True) == {}


# --- Links ---


def test_link_create_rejects_self_loop() -> None:
    with pytest.raises(ValidationError, match="must differ"):
        LinkCreate(port_a_id=5, port_b_id=5, link_type=LinkType.copper)


def test_link_create_accepts_distinct_ports() -> None:
    payload = LinkCreate(port_a_id=5, port_b_id=7, link_type=LinkType.fiber)
    assert payload.port_a_id == 5
    assert payload.port_b_id == 7
