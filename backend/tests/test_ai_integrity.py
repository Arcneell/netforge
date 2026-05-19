"""Unit tests for the deterministic integrity-check service.

Each check fans out into a couple of `db.execute()` calls. We script the
mocked session with the right side-effects and verify the returned
`IntegrityIssue`s match the expected severity / title / entity references.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.ai.integrity import (
    _check_duplicate_macs,
    _check_orphan_assigned_ips,
    _check_port_label_collisions,
    _check_subnets_without_gateway,
    _check_switches_without_ports,
    _check_vlans_without_subnet,
    run_all_checks,
)


def _scalars(rows: list) -> MagicMock:
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=rows)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    return result


def _all_rows(rows: list) -> MagicMock:
    result = MagicMock()
    result.all = MagicMock(return_value=rows)
    return result


@pytest.mark.asyncio
async def test_duplicate_macs_empty_when_no_dups() -> None:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_all_rows([]))
    assert await _check_duplicate_macs(db) == []


@pytest.mark.asyncio
async def test_duplicate_macs_flags_each_repeated_value() -> None:
    """Two distinct MACs each shared by two IPs → two issues."""
    db = AsyncMock()
    ip1 = SimpleNamespace(id=1, address="10.0.0.1", mac="aa:bb:cc:dd:ee:ff")
    ip2 = SimpleNamespace(id=2, address="10.0.0.2", mac="aa:bb:cc:dd:ee:ff")
    ip3 = SimpleNamespace(id=3, address="10.0.0.3", mac="11:22:33:44:55:66")
    ip4 = SimpleNamespace(id=4, address="10.0.0.4", mac="11:22:33:44:55:66")
    # Sequence: aggregate query then one fetch per mac group.
    db.execute = AsyncMock(
        side_effect=[
            _all_rows([("aa:bb:cc:dd:ee:ff", 2), ("11:22:33:44:55:66", 2)]),
            _scalars([ip1, ip2]),
            _scalars([ip3, ip4]),
        ]
    )
    issues = await _check_duplicate_macs(db)
    assert len(issues) == 2
    assert all(i.severity == "warning" for i in issues)
    assert {i.title for i in issues} == {
        "Duplicate MAC address aa:bb:cc:dd:ee:ff",
        "Duplicate MAC address 11:22:33:44:55:66",
    }
    # Affected entities count matches the IPs found per mac.
    assert all(len(i.affected_entities) == 2 for i in issues)


@pytest.mark.asyncio
async def test_orphan_assigned_ips() -> None:
    db = AsyncMock()
    ip = SimpleNamespace(id=42, address="192.168.0.5")
    db.execute = AsyncMock(return_value=_scalars([ip]))
    issues = await _check_orphan_assigned_ips(db)
    assert len(issues) == 1
    assert issues[0].severity == "info"
    assert issues[0].affected_entities == [
        {"type": "ip", "id": 42, "name": "192.168.0.5"}
    ]


@pytest.mark.asyncio
async def test_subnets_without_gateway_flags_each() -> None:
    db = AsyncMock()
    s1 = SimpleNamespace(id=1, cidr="10.0.0.0/24")
    s2 = SimpleNamespace(id=2, cidr="172.16.0.0/16")
    db.execute = AsyncMock(return_value=_scalars([s1, s2]))
    issues = await _check_subnets_without_gateway(db)
    assert len(issues) == 1  # one card aggregating both
    assert issues[0].severity == "info"
    assert len(issues[0].affected_entities) == 2


@pytest.mark.asyncio
async def test_switches_without_ports() -> None:
    db = AsyncMock()
    sw = SimpleNamespace(id=10, name="SW-EMPTY-01")
    db.execute = AsyncMock(return_value=_all_rows([(sw, 0)]))
    issues = await _check_switches_without_ports(db)
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].affected_entities == [{"type": "switch", "id": 10, "name": "SW-EMPTY-01"}]


@pytest.mark.asyncio
async def test_vlans_without_subnet() -> None:
    """A VLAN referenced by zero subnets surfaces; one referenced doesn't."""
    db = AsyncMock()
    v1 = SimpleNamespace(id=1, vlan_id=10, name="data")
    v2 = SimpleNamespace(id=2, vlan_id=20, name="iot")
    # subnets reference only v1.
    db.execute = AsyncMock(
        side_effect=[
            _scalars([1]),  # referenced vlan ids
            _scalars([v1, v2]),  # all vlans
        ]
    )
    issues = await _check_vlans_without_subnet(db)
    assert len(issues) == 1
    assert issues[0].severity == "info"
    assert issues[0].affected_entities[0]["id"] == 2


@pytest.mark.asyncio
async def test_port_label_collisions_groups_by_switch() -> None:
    db = AsyncMock()
    sw = SimpleNamespace(id=10, name="SW-CORE-01")
    p1 = SimpleNamespace(id=100, number=24, label="uplink")
    p2 = SimpleNamespace(id=101, number=25, label="Uplink")
    db.execute = AsyncMock(
        side_effect=[
            # aggregate: one (switch_id, lower(label), count)
            _all_rows([SimpleNamespace(switch_id=10, lbl="uplink", n=2)]),
            # switches in the set
            _scalars([sw]),
            # ports matching that (switch_id, label)
            _scalars([p1, p2]),
        ]
    )
    issues = await _check_port_label_collisions(db)
    assert len(issues) == 1
    assert "SW-CORE-01" in issues[0].title
    # 1 switch chip + 2 port chips
    assert len(issues[0].affected_entities) == 3


@pytest.mark.asyncio
async def test_run_all_checks_orders_by_severity() -> None:
    """`run_all_checks` should hand back critical → warning → info regardless
    of detector order."""
    db = AsyncMock()
    # Return findings only from a single detector, so we know the order.
    # We monkey-patch every check via the module's `_check_*` names except the
    # one we want, but it's easier to script `db.execute` such that one
    # detector returns a warning and another returns an info.
    db.execute = AsyncMock(
        side_effect=[
            _all_rows([]),  # macs: empty
            _scalars(
                [SimpleNamespace(id=1, address="10.0.0.1")]
            ),  # orphan ips → info
            _scalars(
                [SimpleNamespace(id=1, cidr="10.0.0.0/24")]
            ),  # subnets without gateway → info
            _all_rows(
                [(SimpleNamespace(id=2, name="SW-X"), 0)]
            ),  # switches without ports → warning
            _scalars([]),  # vlans-without-subnet: referenced
            _scalars([]),  # vlans-without-subnet: all
            _all_rows([]),  # port label collisions: none
        ]
    )
    issues = await run_all_checks(db)
    severities = [i.severity for i in issues]
    # Warning comes before info.
    assert severities == sorted(severities, key=lambda s: {"critical": 0, "warning": 1, "info": 2}[s])
