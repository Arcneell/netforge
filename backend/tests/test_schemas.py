"""Schema validation tests — pure Pydantic, no DB."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.ip import IpCreate, IpStatus
from app.schemas.room import RoomCreate
from app.schemas.site import SiteCreate
from app.schemas.subnet import SubnetCreate
from app.schemas.vlan import VlanCreate


# --- Sites ---


def test_site_create_accepts_alphanumeric_code() -> None:
    payload = SiteCreate(code="HQ_01-PAR", name="Paris HQ")
    assert payload.code == "HQ_01-PAR"
    assert payload.address is None


def test_site_create_rejects_invalid_code() -> None:
    with pytest.raises(ValidationError):
        SiteCreate(code="HQ Paris!", name="...")


def test_site_create_rejects_empty_name() -> None:
    with pytest.raises(ValidationError):
        SiteCreate(code="HQ", name="")


# --- Rooms ---


def test_room_create_requires_positive_site_id() -> None:
    with pytest.raises(ValidationError):
        RoomCreate(site_id=0, code="A1")


# --- VLANs ---


def test_vlan_id_range() -> None:
    VlanCreate(vlan_id=1, name="MGMT")
    VlanCreate(vlan_id=4094, name="MAX")
    with pytest.raises(ValidationError):
        VlanCreate(vlan_id=0, name="zero")
    with pytest.raises(ValidationError):
        VlanCreate(vlan_id=4095, name="too-big")


def test_vlan_color_must_be_hex() -> None:
    VlanCreate(vlan_id=10, name="OK", color="#abcDEF")
    with pytest.raises(ValidationError):
        VlanCreate(vlan_id=10, name="bad", color="red")


# --- Subnets ---


def test_subnet_create_canonicalizes_cidr() -> None:
    payload = SubnetCreate(cidr="10.0.30.0/24", site_id=1)
    assert payload.cidr == "10.0.30.0/24"


def test_subnet_create_accepts_host_bits_set() -> None:
    # IPv4Network(strict=False) silently normalises 10.0.30.5/24 → 10.0.30.0/24.
    payload = SubnetCreate(cidr="10.0.30.5/24", site_id=1)
    assert payload.cidr == "10.0.30.0/24"


def test_subnet_create_rejects_garbage_cidr() -> None:
    with pytest.raises(ValidationError):
        SubnetCreate(cidr="not-a-cidr", site_id=1)


def test_subnet_gateway_validates() -> None:
    payload = SubnetCreate(cidr="10.0.30.0/24", site_id=1, gateway="10.0.30.1")
    assert payload.gateway == "10.0.30.1"
    with pytest.raises(ValidationError):
        SubnetCreate(cidr="10.0.30.0/24", site_id=1, gateway="999.0.0.1")


# --- IPs ---


def test_ip_create_validates_address() -> None:
    payload = IpCreate(
        subnet_id=1, address="10.0.30.42", status=IpStatus.assigned
    )
    assert payload.address == "10.0.30.42"
    with pytest.raises(ValidationError):
        IpCreate(subnet_id=1, address="not-an-ip", status=IpStatus.assigned)


def test_ip_mac_must_be_canonical() -> None:
    IpCreate(
        subnet_id=1,
        address="10.0.30.42",
        mac="aa:bb:cc:dd:ee:ff",
        status=IpStatus.assigned,
    )
    with pytest.raises(ValidationError):
        IpCreate(
            subnet_id=1,
            address="10.0.30.42",
            mac="aabbccddeeff",
            status=IpStatus.assigned,
        )


def test_ip_status_must_be_valid_enum() -> None:
    with pytest.raises(ValidationError):
        IpCreate(subnet_id=1, address="10.0.30.42", status="unknown")  # type: ignore[arg-type]
