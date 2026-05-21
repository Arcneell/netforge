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
    _check_subnet_capacity,
    _check_subnets_without_gateway,
    _check_switch_port_capacity,
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
    assert await _check_duplicate_macs(db, "en") == []


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
    issues = await _check_duplicate_macs(db, "en")
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
    issues = await _check_orphan_assigned_ips(db, "en")
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
    issues = await _check_subnets_without_gateway(db, "en")
    assert len(issues) == 1  # one card aggregating both
    assert issues[0].severity == "info"
    assert len(issues[0].affected_entities) == 2


@pytest.mark.asyncio
async def test_switches_without_ports() -> None:
    db = AsyncMock()
    sw = SimpleNamespace(id=10, name="SW-EMPTY-01")
    db.execute = AsyncMock(return_value=_all_rows([(sw, 0)]))
    issues = await _check_switches_without_ports(db, "en")
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
    issues = await _check_vlans_without_subnet(db, "en")
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
    issues = await _check_port_label_collisions(db, "en")
    assert len(issues) == 1
    assert "SW-CORE-01" in issues[0].title
    # 1 switch chip + 2 port chips
    assert len(issues[0].affected_entities) == 3


@pytest.mark.asyncio
async def test_subnet_capacity_flags_over_90pct() -> None:
    """A /24 with 230 assigned/dhcp IPs (out of 254 usable) → warning at 90%.
    A /24 with 30 IPs (≈12%) stays quiet."""
    full = SimpleNamespace(id=1, cidr="10.0.0.0/24")
    sparse = SimpleNamespace(id=2, cidr="10.0.1.0/24")
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalars([full, sparse]),  # subnets
            _all_rows([(1, 230), (2, 30)]),  # ip counts per subnet
        ]
    )
    issues = await _check_subnet_capacity(db, "en")
    assert len(issues) == 1
    issue = issues[0]
    assert issue.severity == "warning"
    assert "10.0.0.0/24" in issue.title
    # 230/254 ≈ 90%
    assert "90%" in issue.title
    assert issue.affected_entities[0]["id"] == 1


@pytest.mark.asyncio
async def test_subnet_capacity_full_is_critical() -> None:
    """100% utilisation gets bumped to `critical` — there's no slack left,
    the next allocation will fail."""
    full = SimpleNamespace(id=1, cidr="10.0.0.0/30")  # 2 usable
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalars([full]),
            _all_rows([(1, 2)]),
        ]
    )
    issues = await _check_subnet_capacity(db, "en")
    assert len(issues) == 1
    assert issues[0].severity == "critical"
    assert "100%" in issues[0].title


@pytest.mark.asyncio
async def test_subnet_capacity_handles_slash_31_specially() -> None:
    """/31 (RFC 3021 point-to-point) and /32 (loopback) keep all addresses
    as usable. A /31 with 1 IP is at 50%, not over the threshold, and must
    not raise — without the special case the math would treat usable as 0
    and divide-by-zero (caught by the `usable <= 0` guard but the test
    pins the intent)."""
    ptp = SimpleNamespace(id=1, cidr="10.0.0.0/31")
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalars([ptp]),
            _all_rows([(1, 1)]),  # 50% used
        ]
    )
    assert await _check_subnet_capacity(db, "en") == []


@pytest.mark.asyncio
async def test_switch_port_capacity_flags_over_90pct() -> None:
    """A 48-port switch with 45 ports in use (94%) trips the warning."""
    sw = SimpleNamespace(id=10, name="SW-CORE-01")
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalars([sw]),  # switches
            _all_rows([SimpleNamespace(switch_id=10, total=48, in_use=45)]),
        ]
    )
    issues = await _check_switch_port_capacity(db, "en")
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert "SW-CORE-01" in issues[0].title
    assert "93%" in issues[0].title or "94%" in issues[0].title


@pytest.mark.asyncio
async def test_switch_port_capacity_excludes_disabled_ports_with_stale_device() -> None:
    """Regression for Codex P2 on PR #58: a port that's been administratively
    disabled but still carries a `connected_device_id` from a previous
    assignment must NOT count toward `in_use`. We simulate the aggregate the
    DB would now return (with the `mode != disabled` filter applied) and
    verify the detector treats the switch as 5/48 (10%), well below the
    90% threshold, instead of the pre-fix 6/48 that would still creep up.

    The aggregate value is what the DB returns AFTER the filter — the test
    pins the contract, not the SQL itself."""
    sw = SimpleNamespace(id=10, name="SW-X")
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalars([sw]),
            _all_rows([SimpleNamespace(switch_id=10, total=48, in_use=5)]),
        ]
    )
    assert await _check_switch_port_capacity(db, "en") == []


@pytest.mark.asyncio
async def test_switch_port_capacity_ignores_switches_without_ports() -> None:
    """A switch with no Port rows is already handled by the dedicated
    `_check_switches_without_ports` detector — the capacity one must not
    double-warn (would say `0% used` and trip a divide-by-zero if not
    guarded)."""
    sw = SimpleNamespace(id=10, name="SW-X")
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalars([sw]),
            _all_rows([]),  # no aggregate rows = switch has no ports
        ]
    )
    assert await _check_switch_port_capacity(db, "en") == []


@pytest.mark.asyncio
async def test_orphan_assigned_ips_localized_french() -> None:
    """The FR locale flips title/description to French strings so the UI
    doesn't show English text when the operator is on the FR locale."""
    db = AsyncMock()
    ip = SimpleNamespace(id=1, address="10.0.0.1")
    db.execute = AsyncMock(return_value=_scalars([ip]))
    issues = await _check_orphan_assigned_ips(db, "fr")
    assert len(issues) == 1
    assert "assignée" in issues[0].title.lower() or "ip" in issues[0].title.lower()
    # The recommendation must definitely be French.
    assert "réservée" in issues[0].recommendation or "groupée" in issues[0].recommendation


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
            _scalars([]),  # subnet capacity: no subnets → no issues
            _all_rows([]),  # subnet capacity: ip counts (not reached)
            _scalars([]),  # switch port capacity: no switches → no issues
            _all_rows([]),  # switch port capacity: aggregates (not reached)
        ]
    )
    issues = await run_all_checks(db, accept_language="en")
    severities = [i.severity for i in issues]
    # Warning comes before info.
    assert severities == sorted(severities, key=lambda s: {"critical": 0, "warning": 1, "info": 2}[s])
