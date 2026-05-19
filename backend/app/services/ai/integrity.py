"""Deterministic integrity checks over the NetForge inventory.

This complements the LLM-powered advisor with a set of *fast, deterministic*
detectors that don't need a network round-trip or a token budget:
- Duplicate MAC addresses across IPs.
- "Assigned" IPs without a `device_id` (data-entry mistake).
- Subnets missing a gateway (often intentional but worth surfacing).
- Switches with `port_count = 0` or no `Port` rows.
- VLANs without any subnet referencing them.
- Case-insensitive port-label collisions inside a single switch.

Each detector returns zero or more `IntegrityIssue` dicts shaped exactly
like the LLM `Insight` payload, so the Vue card components can render
either source without branching.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import Site
from app.models.ip import Ip, IpStatus
from app.models.port import Port
from app.models.subnet import Subnet
from app.models.switch import Switch
from app.models.vlan import Vlan


@dataclass
class IntegrityIssue:
    """Same shape as `schemas.ai.InsightRead` so the UI re-uses the existing
    card components."""

    severity: str  # info | warning | critical
    category: str  # one of the InsightCategory enum values
    title: str
    description: str
    recommendation: str
    # Each entry: {"type": "device"|"ip"|..., "id": int, "name": str|None}.
    affected_entities: list[dict[str, Any]]


async def run_all_checks(db: AsyncSession) -> list[IntegrityIssue]:
    """Run every detector and concatenate their findings.

    Order matters for UI predictability (critical first). Each detector is
    independent — a slow query doesn't block the others (sequential here for
    simplicity; the whole batch should still finish in under a second).
    """
    issues: list[IntegrityIssue] = []
    issues.extend(await _check_duplicate_macs(db))
    issues.extend(await _check_orphan_assigned_ips(db))
    issues.extend(await _check_subnets_without_gateway(db))
    issues.extend(await _check_switches_without_ports(db))
    issues.extend(await _check_vlans_without_subnet(db))
    issues.extend(await _check_port_label_collisions(db))
    # Sort: critical → warning → info, then keep insertion order within each.
    rank = {"critical": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda i: rank.get(i.severity, 99))
    return issues


async def _check_duplicate_macs(db: AsyncSession) -> list[IntegrityIssue]:
    """Two IPs sharing a MAC almost certainly mean a data-entry error — the
    same NIC can't be in two subnets. (Aggregated devices behind a router
    keep their own MAC; bonding shows up as one MAC per side.)"""
    stmt = (
        select(Ip.mac, func.count(Ip.id).label("n"))
        .where(Ip.mac.is_not(None))
        .group_by(Ip.mac)
        .having(func.count(Ip.id) > 1)
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        return []
    issues: list[IntegrityIssue] = []
    for mac, _n in rows:
        ips = (
            (
                await db.execute(
                    select(Ip).where(Ip.mac == mac)
                )
            )
            .scalars()
            .all()
        )
        entities = [
            {"type": "ip", "id": ip.id, "name": str(ip.address)} for ip in ips
        ]
        issues.append(
            IntegrityIssue(
                severity="warning",
                category="other",
                title=f"Duplicate MAC address {mac}",
                description=(
                    f"{len(ips)} IP records share the MAC address `{mac}`. "
                    f"A given network interface can only appear once — review and merge or correct."
                ),
                recommendation=(
                    "Open each IP, confirm which one actually owns the MAC, "
                    "and clear the MAC field on the others."
                ),
                affected_entities=entities,
            )
        )
    return issues


async def _check_orphan_assigned_ips(db: AsyncSession) -> list[IntegrityIssue]:
    """An IP in `assigned` status without a `device_id` is a mistake — either
    it's actually `reserved`, or somebody forgot to link the device."""
    stmt = select(Ip).where(
        Ip.status == IpStatus.assigned,
        Ip.device_id.is_(None),
    )
    ips = (await db.execute(stmt)).scalars().all()
    if not ips:
        return []
    entities = [{"type": "ip", "id": ip.id, "name": str(ip.address)} for ip in ips]
    return [
        IntegrityIssue(
            severity="info",
            category="other",
            title=f"{len(ips)} assigned IP(s) missing a device link",
            description=(
                "These IPs are marked as **assigned** but have no `device_id`. "
                "Either link them to the real device, or downgrade them to "
                "`reserved` if no host owns them yet."
            ),
            recommendation=(
                "Bulk-edit from the subnet view: set the device on each row "
                "(or change the status to `reserved`)."
            ),
            affected_entities=entities,
        )
    ]


async def _check_subnets_without_gateway(db: AsyncSession) -> list[IntegrityIssue]:
    """Subnets without a gateway can be intentional (loopback /32, point-to-
    point /30) — surface as `info` rather than `warning` so the operator
    isn't nagged about legitimate ones."""
    subnets = (
        (await db.execute(select(Subnet).where(Subnet.gateway.is_(None))))
        .scalars()
        .all()
    )
    if not subnets:
        return []
    entities = [
        {"type": "subnet", "id": s.id, "name": str(s.cidr)} for s in subnets
    ]
    return [
        IntegrityIssue(
            severity="info",
            category="naming",
            title=f"{len(subnets)} subnet(s) without a gateway",
            description=(
                "These subnets have no recorded gateway. That's expected for "
                "loopback / point-to-point ranges, but for end-user VLANs it "
                "usually means the gateway field was simply not filled in."
            ),
            recommendation=(
                "Edit each subnet and set the gateway, or leave it blank if "
                "the range really doesn't have one."
            ),
            affected_entities=entities,
        )
    ]


async def _check_switches_without_ports(db: AsyncSession) -> list[IntegrityIssue]:
    """A switch with `port_count = 0` is almost always a half-created record —
    the create flow auto-generates ports based on `port_count`."""
    stmt = (
        select(Switch, func.count(Port.id).label("n"))
        .outerjoin(Port, Port.switch_id == Switch.id)
        .group_by(Switch.id)
        .having(func.count(Port.id) == 0)
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        return []
    entities = [{"type": "switch", "id": sw.id, "name": sw.name} for sw, _ in rows]
    return [
        IntegrityIssue(
            severity="warning",
            category="other",
            title=f"{len(rows)} switch(es) have zero ports",
            description=(
                "These switches exist in the inventory but have no `Port` rows. "
                "Topology views and link suggestions will skip them entirely."
            ),
            recommendation=(
                "Open each switch and re-enter the port count — the system "
                "will auto-generate the missing rows."
            ),
            affected_entities=entities,
        )
    ]


async def _check_vlans_without_subnet(db: AsyncSession) -> list[IntegrityIssue]:
    """A VLAN that no subnet references is dead weight or a forgotten setup —
    flag it as info; the operator can confirm or delete."""
    referenced = (
        await db.execute(select(Subnet.vlan_id).where(Subnet.vlan_id.is_not(None)))
    ).scalars().all()
    referenced_set = set(referenced)
    vlans = (await db.execute(select(Vlan))).scalars().all()
    orphans = [v for v in vlans if v.id not in referenced_set]
    if not orphans:
        return []
    entities = [
        {"type": "vlan", "id": v.id, "name": f"VLAN {v.vlan_id} — {v.name}"}
        for v in orphans
    ]
    return [
        IntegrityIssue(
            severity="info",
            category="segmentation",
            title=f"{len(orphans)} VLAN(s) not used by any subnet",
            description=(
                "These VLANs are defined but no subnet maps to them. They may "
                "be reserved on purpose, or they may be left-overs from an old "
                "configuration."
            ),
            recommendation=(
                "Either bind a subnet to each VLAN or delete the unused entries."
            ),
            affected_entities=entities,
        )
    ]


async def _check_port_label_collisions(db: AsyncSession) -> list[IntegrityIssue]:
    """Two ports on the same switch sharing a label (case-insensitive) is a
    typo or a paste mistake. Genuine labels — port numbers, named uplinks —
    are unique on a single chassis."""
    stmt = (
        select(
            Port.switch_id.label("switch_id"),
            func.lower(Port.label).label("lbl"),
            func.count(Port.id).label("n"),
        )
        .where(Port.label.is_not(None))
        .where(Port.label != "")
        .group_by(Port.switch_id, func.lower(Port.label))
        .having(func.count(Port.id) > 1)
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        return []
    issues: list[IntegrityIssue] = []
    # We resolve switch names in one extra query for nicer chips.
    switch_ids = {r.switch_id for r in rows}
    switches_by_id = {
        s.id: s
        for s in (
            await db.execute(select(Switch).where(Switch.id.in_(switch_ids)))
        )
        .scalars()
        .all()
    }
    for r in rows:
        sw = switches_by_id.get(r.switch_id)
        sw_name = sw.name if sw else f"switch #{r.switch_id}"
        ports = (
            await db.execute(
                select(Port)
                .where(Port.switch_id == r.switch_id)
                .where(func.lower(Port.label) == r.lbl)
            )
        ).scalars().all()
        entities = (
            [{"type": "switch", "id": r.switch_id, "name": sw_name}]
            + [{"type": "port", "id": p.id, "name": p.label or f"port {p.number}"} for p in ports]
        )
        issues.append(
            IntegrityIssue(
                severity="info",
                category="naming",
                title=f"Duplicate port label `{r.lbl}` on {sw_name}",
                description=(
                    f"{r.n} ports on switch `{sw_name}` share the label `{r.lbl}` "
                    f"(case-insensitive). Likely a copy-paste mistake."
                ),
                recommendation=(
                    "Open the switch detail view and rename the duplicates to "
                    "reflect each port's actual role."
                ),
                affected_entities=entities,
            )
        )
    return issues


# Suppress unused-import warning — Site is imported to keep the SQLAlchemy
# metadata graph eager-resolved when this module is imported standalone.
_ = Site
