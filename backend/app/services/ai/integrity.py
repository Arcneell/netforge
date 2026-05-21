"""Deterministic integrity checks over the NetForge inventory.

This complements the LLM-powered advisor with a set of *fast, deterministic*
detectors that don't need a network round-trip or a token budget:
- Duplicate MAC addresses across IPs.
- "Assigned" IPs without a `device_id` (data-entry mistake).
- Subnets missing a gateway (often intentional but worth surfacing).
- Switches with `port_count = 0` or no `Port` rows.
- VLANs without any subnet referencing them.
- Case-insensitive port-label collisions inside a single switch.
- **Subnets ≥ 90% full** — capacity warning so operators see the squeeze
  coming instead of getting blindsided by a DHCP exhaustion.
- **Switches ≥ 90% port utilisation** — same idea on the port side.

Each detector returns zero or more `IntegrityIssue` dicts shaped exactly
like the LLM `Insight` payload, so the Vue card components can render
either source without branching.
"""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import IPv4Network
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import Site
from app.models.ip import Ip, IpStatus
from app.models.port import Port, PortMode
from app.models.subnet import Subnet
from app.models.switch import Switch
from app.models.vlan import Vlan
from app.services.ai.locale import _parse_primary_tag

# A subnet or switch crossing this threshold is worth a `warning` insight.
# 90% is the cliff most ops teams target — past it, ad-hoc allocations
# start failing and recovery is painful.
_CAPACITY_WARN_PCT = 90

# Embedded translation table — these strings are server-rendered (no LLM
# call, so the language_instruction shim used elsewhere doesn't apply) and
# we don't want to round-trip them through the frontend i18n bundle either,
# because the message format is dynamic (counts, MAC values, switch names).
# Keep the dictionary keyed by `locale → key` so adding a third language
# means adding one block, not threading a context through every detector.
_STRINGS: dict[str, dict[str, str]] = {
    "fr": {
        "dup_mac_title": "Adresse MAC en double {mac}",
        "dup_mac_desc": (
            "{count} adresses IP partagent la MAC `{mac}`. Une interface réseau "
            "donnée ne peut figurer qu'une fois — vérifiez et corrigez ou fusionnez."
        ),
        "dup_mac_reco": (
            "Ouvrez chaque IP, identifiez celle qui possède réellement la MAC, "
            "et videz le champ MAC sur les autres."
        ),
        "orphan_ip_title": "{count} IP(s) marquée(s) « assignée » sans équipement lié",
        "orphan_ip_desc": (
            "Ces IPs ont le statut **assignée** mais aucun `device_id`. Liez-les à "
            "l'équipement réel ou repassez-les en `réservée` si aucun hôte ne les détient."
        ),
        "orphan_ip_reco": (
            "Édition groupée depuis la vue du subnet : renseignez l'équipement sur "
            "chaque ligne (ou changez le statut en `réservée`)."
        ),
        "no_gateway_title": "{count} subnet(s) sans passerelle",
        "no_gateway_desc": (
            "Ces subnets n'ont pas de passerelle enregistrée. C'est normal pour "
            "des loopbacks ou des liens point-à-point, mais pour un VLAN utilisateur "
            "cela trahit en général un champ resté vide."
        ),
        "no_gateway_reco": (
            "Modifiez chaque subnet et renseignez la passerelle, ou laissez vide si "
            "le réseau n'en a pas."
        ),
        "switch_no_ports_title": "{count} switch(es) sans aucun port",
        "switch_no_ports_desc": (
            "Ces switches existent dans l'inventaire mais n'ont aucune ligne dans "
            "`Port`. Les vues topologie et les suggestions de liens les ignoreront."
        ),
        "switch_no_ports_reco": (
            "Ouvrez chaque switch et ressaisissez le nombre de ports — le système "
            "régénérera automatiquement les lignes manquantes."
        ),
        "orphan_vlan_title": "{count} VLAN(s) utilisé(s) par aucun subnet",
        "orphan_vlan_desc": (
            "Ces VLANs sont définis mais aucun subnet n'y fait référence. "
            "Réservation volontaire, ou héritage d'une ancienne configuration."
        ),
        "orphan_vlan_reco": "Attachez un subnet à chaque VLAN, ou supprimez les entrées inutiles.",
        "port_label_dup_title": "Libellé de port `{label}` en double sur {switch}",
        "port_label_dup_desc": (
            "{count} ports du switch `{switch}` partagent le libellé `{label}` "
            "(sans tenir compte de la casse). Probable erreur de copier-coller."
        ),
        "port_label_dup_reco": (
            "Ouvrez la vue détail du switch et renommez les doublons pour qu'ils "
            "reflètent le rôle réel de chaque port."
        ),
        "subnet_capacity_title": "Subnet `{cidr}` rempli à {pct}%",
        "subnet_capacity_desc": (
            "{used}/{usable} adresses utiles sont consommées sur `{cidr}`. "
            "À ce rythme, la prochaine attribution risque d'échouer faute de "
            "place — planifiez un découpage ou un /23 plus large avant la "
            "saturation."
        ),
        "subnet_capacity_reco": (
            "Soit attribuez un subnet additionnel à ce VLAN/site, soit migrez "
            "vers un préfixe plus large (`/23` au lieu de `/24` par exemple). "
            "L'advisor LLM peut suggérer un découpage adapté à votre topologie."
        ),
        "switch_port_capacity_title": "Switch `{switch}` à {pct}% de ports utilisés",
        "switch_port_capacity_desc": (
            "{used}/{total} ports actifs ou raccordés sur `{switch}`. Quand un "
            "switch passe les 90% il n'y a plus de marge pour brancher un "
            "nouvel équipement sans rejouer le câblage."
        ),
        "switch_port_capacity_reco": (
            "Prévoyez un châssis additionnel ou un module d'extension, ou "
            "auditez les ports `disabled` pour récupérer de la capacité."
        ),
        "fallback_port_default_name": "port {n}",
    },
    "en": {
        "dup_mac_title": "Duplicate MAC address {mac}",
        "dup_mac_desc": (
            "{count} IP records share the MAC address `{mac}`. A given network "
            "interface can only appear once — review and merge or correct."
        ),
        "dup_mac_reco": (
            "Open each IP, confirm which one actually owns the MAC, and clear the "
            "MAC field on the others."
        ),
        "orphan_ip_title": "{count} assigned IP(s) missing a device link",
        "orphan_ip_desc": (
            "These IPs are marked as **assigned** but have no `device_id`. Either "
            "link them to the real device, or downgrade them to `reserved` if no "
            "host owns them yet."
        ),
        "orphan_ip_reco": (
            "Bulk-edit from the subnet view: set the device on each row (or change "
            "the status to `reserved`)."
        ),
        "no_gateway_title": "{count} subnet(s) without a gateway",
        "no_gateway_desc": (
            "These subnets have no recorded gateway. That's expected for loopback "
            "or point-to-point ranges, but for end-user VLANs it usually means the "
            "gateway field was simply not filled in."
        ),
        "no_gateway_reco": (
            "Edit each subnet and set the gateway, or leave it blank if the range "
            "really doesn't have one."
        ),
        "switch_no_ports_title": "{count} switch(es) have zero ports",
        "switch_no_ports_desc": (
            "These switches exist in the inventory but have no `Port` rows. "
            "Topology views and link suggestions will skip them entirely."
        ),
        "switch_no_ports_reco": (
            "Open each switch and re-enter the port count — the system will "
            "auto-generate the missing rows."
        ),
        "orphan_vlan_title": "{count} VLAN(s) not used by any subnet",
        "orphan_vlan_desc": (
            "These VLANs are defined but no subnet maps to them. They may be "
            "reserved on purpose, or they may be left-overs from an old "
            "configuration."
        ),
        "orphan_vlan_reco": "Either bind a subnet to each VLAN or delete the unused entries.",
        "port_label_dup_title": "Duplicate port label `{label}` on {switch}",
        "port_label_dup_desc": (
            "{count} ports on switch `{switch}` share the label `{label}` "
            "(case-insensitive). Likely a copy-paste mistake."
        ),
        "port_label_dup_reco": (
            "Open the switch detail view and rename the duplicates to reflect "
            "each port's actual role."
        ),
        "subnet_capacity_title": "Subnet `{cidr}` is {pct}% full",
        "subnet_capacity_desc": (
            "{used}/{usable} usable addresses consumed on `{cidr}`. At this "
            "rate the next allocation may fail for lack of space — plan a "
            "split or a larger prefix before exhaustion."
        ),
        "subnet_capacity_reco": (
            "Either allocate an additional subnet for this VLAN/site, or "
            "renumber to a larger prefix (e.g. `/23` instead of `/24`). The "
            "LLM advisor can suggest a split tailored to your topology."
        ),
        "switch_port_capacity_title": "Switch `{switch}` is at {pct}% port usage",
        "switch_port_capacity_desc": (
            "{used}/{total} ports are active or patched on `{switch}`. Past "
            "90% there's no headroom left to plug in a new device without "
            "reshuffling cabling."
        ),
        "switch_port_capacity_reco": (
            "Plan for an extra chassis or a stack module, or audit the "
            "`disabled` ports to reclaim capacity."
        ),
        "fallback_port_default_name": "port {n}",
    },
}


def _t(locale: str, key: str, **kwargs: Any) -> str:
    bundle = _STRINGS.get(locale, _STRINGS["en"])
    template = bundle.get(key, _STRINGS["en"].get(key, key))
    return template.format(**kwargs)


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


async def run_all_checks(
    db: AsyncSession, *, accept_language: str | None = None
) -> list[IntegrityIssue]:
    """Run every detector and concatenate their findings.

    Order matters for UI predictability (critical first). Each detector is
    independent — a slow query doesn't block the others (sequential here for
    simplicity; the whole batch should still finish in under a second).

    `accept_language` carries the request header so the issue titles /
    descriptions come back in the operator's UI language (FR/EN, falls
    back to EN — matches the rest of the AI surface).
    """
    locale = _parse_primary_tag(accept_language) if accept_language else "en"
    if locale not in _STRINGS:
        locale = "en"
    issues: list[IntegrityIssue] = []
    issues.extend(await _check_duplicate_macs(db, locale))
    issues.extend(await _check_orphan_assigned_ips(db, locale))
    issues.extend(await _check_subnets_without_gateway(db, locale))
    issues.extend(await _check_switches_without_ports(db, locale))
    issues.extend(await _check_vlans_without_subnet(db, locale))
    issues.extend(await _check_port_label_collisions(db, locale))
    issues.extend(await _check_subnet_capacity(db, locale))
    issues.extend(await _check_switch_port_capacity(db, locale))
    # Sort: critical → warning → info, then keep insertion order within each.
    rank = {"critical": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda i: rank.get(i.severity, 99))
    return issues


async def _check_duplicate_macs(db: AsyncSession, locale: str) -> list[IntegrityIssue]:
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
                title=_t(locale, "dup_mac_title", mac=mac),
                description=_t(locale, "dup_mac_desc", count=len(ips), mac=mac),
                recommendation=_t(locale, "dup_mac_reco"),
                affected_entities=entities,
            )
        )
    return issues


async def _check_orphan_assigned_ips(db: AsyncSession, locale: str) -> list[IntegrityIssue]:
    """An IP in `assigned` status without a `device_id` AND not bound to any
    port is a mistake — either it's actually `reserved`, or somebody forgot
    to link the device. An IP that lives on a port (mgmt-IPs on switches,
    typically) is a valid assignment without a device record."""
    # Sub-select: every IP referenced by any port.connected_ip_id. Excluding
    # them keeps switch management IPs out of the orphan report.
    port_linked_ips = select(Port.connected_ip_id).where(Port.connected_ip_id.is_not(None))
    stmt = select(Ip).where(
        Ip.status == IpStatus.assigned,
        Ip.device_id.is_(None),
        Ip.id.notin_(port_linked_ips),
    )
    ips = (await db.execute(stmt)).scalars().all()
    if not ips:
        return []
    entities = [{"type": "ip", "id": ip.id, "name": str(ip.address)} for ip in ips]
    return [
        IntegrityIssue(
            severity="info",
            category="other",
            title=_t(locale, "orphan_ip_title", count=len(ips)),
            description=_t(locale, "orphan_ip_desc"),
            recommendation=_t(locale, "orphan_ip_reco"),
            affected_entities=entities,
        )
    ]


async def _check_subnets_without_gateway(db: AsyncSession, locale: str) -> list[IntegrityIssue]:
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
            title=_t(locale, "no_gateway_title", count=len(subnets)),
            description=_t(locale, "no_gateway_desc"),
            recommendation=_t(locale, "no_gateway_reco"),
            affected_entities=entities,
        )
    ]


async def _check_switches_without_ports(db: AsyncSession, locale: str) -> list[IntegrityIssue]:
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
            title=_t(locale, "switch_no_ports_title", count=len(rows)),
            description=_t(locale, "switch_no_ports_desc"),
            recommendation=_t(locale, "switch_no_ports_reco"),
            affected_entities=entities,
        )
    ]


async def _check_vlans_without_subnet(db: AsyncSession, locale: str) -> list[IntegrityIssue]:
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
            title=_t(locale, "orphan_vlan_title", count=len(orphans)),
            description=_t(locale, "orphan_vlan_desc"),
            recommendation=_t(locale, "orphan_vlan_reco"),
            affected_entities=entities,
        )
    ]


async def _check_port_label_collisions(db: AsyncSession, locale: str) -> list[IntegrityIssue]:
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
            + [
                {
                    "type": "port",
                    "id": p.id,
                    "name": p.label or _t(locale, "fallback_port_default_name", n=p.number),
                }
                for p in ports
            ]
        )
        issues.append(
            IntegrityIssue(
                severity="info",
                category="naming",
                title=_t(locale, "port_label_dup_title", label=r.lbl, switch=sw_name),
                description=_t(
                    locale, "port_label_dup_desc", count=r.n, switch=sw_name, label=r.lbl
                ),
                recommendation=_t(locale, "port_label_dup_reco"),
                affected_entities=entities,
            )
        )
    return issues


async def _check_subnet_capacity(db: AsyncSession, locale: str) -> list[IntegrityIssue]:
    """A subnet at >= 90% of usable IPs assigned is one bad week away from
    running out. We count any IP whose status is `assigned` or `dhcp` against
    the subnet's usable address space (the CIDR's full host count minus 2
    for network + broadcast — /31 and /32 keep all addresses)."""
    subnets = (await db.execute(select(Subnet))).scalars().all()
    if not subnets:
        return []
    # Group IPs by subnet in one query so we don't do N+1.
    counts: dict[int, int] = {}
    rows = (
        await db.execute(
            select(Ip.subnet_id, func.count(Ip.id))
            .where(Ip.status.in_([IpStatus.assigned, IpStatus.dhcp]))
            .group_by(Ip.subnet_id)
        )
    ).all()
    for subnet_id, n in rows:
        if subnet_id is not None:
            counts[int(subnet_id)] = int(n)

    issues: list[IntegrityIssue] = []
    for subnet in subnets:
        try:
            net = IPv4Network(str(subnet.cidr), strict=False)
        except ValueError:
            continue
        # Usable host count: prefix /31 and /32 are point-to-point / loopback
        # special cases where every address is usable; otherwise subtract
        # network + broadcast.
        usable = net.num_addresses if net.prefixlen >= 31 else net.num_addresses - 2
        if usable <= 0:
            continue
        used = counts.get(subnet.id, 0)
        pct = (used * 100) // usable
        if pct < _CAPACITY_WARN_PCT:
            continue
        issues.append(
            IntegrityIssue(
                severity="warning" if pct < 100 else "critical",
                category="capacity",
                title=_t(locale, "subnet_capacity_title", cidr=str(subnet.cidr), pct=pct),
                description=_t(
                    locale,
                    "subnet_capacity_desc",
                    cidr=str(subnet.cidr),
                    used=used,
                    usable=usable,
                ),
                recommendation=_t(locale, "subnet_capacity_reco"),
                affected_entities=[
                    {"type": "subnet", "id": subnet.id, "name": str(subnet.cidr)}
                ],
            )
        )
    return issues


async def _check_switch_port_capacity(db: AsyncSession, locale: str) -> list[IntegrityIssue]:
    """A switch with >= 90% of its ports actually in use has no headroom to
    plug something new in. We count a port as "in use" if it's either
    connected to a device, in trunk/hybrid mode, or carrying a tagged-VLAN
    list — anything that isn't a blank `access`-mode port sitting idle.
    `disabled` ports DON'T count: those are reclaimable capacity."""
    switches = (await db.execute(select(Switch))).scalars().all()
    if not switches:
        return []
    # Pull all the per-switch port aggregates in one go. A port counts as
    # "in use" if it has a device wired in, or it's a trunk/hybrid carrying
    # something. Idle `access`-mode ports and `disabled` ports are
    # reclaimable, so they don't count.
    rows = (
        await db.execute(
            select(
                Port.switch_id,
                func.count(Port.id).label("total"),
                func.count(Port.id).filter(
                    (Port.connected_device_id.is_not(None))
                    | (Port.mode.in_([PortMode.trunk, PortMode.hybrid]))
                ).label("in_use"),
            )
            .group_by(Port.switch_id)
        )
    ).all()
    aggregates = {int(r.switch_id): r for r in rows}
    issues: list[IntegrityIssue] = []
    for sw in switches:
        agg = aggregates.get(sw.id)
        # If no Port rows exist the dedicated check already flags it as a
        # warning; we don't double-up here.
        if not agg or agg.total == 0:
            continue
        # Effective capacity = total ports minus the reclaimable disabled
        # ones; in_use already excludes those because they're mode=disabled.
        # We compute the headline percentage against `total` so the operator
        # number matches the rack-view stats they already see.
        pct = (int(agg.in_use) * 100) // int(agg.total)
        if pct < _CAPACITY_WARN_PCT:
            continue
        issues.append(
            IntegrityIssue(
                severity="warning" if pct < 100 else "critical",
                category="capacity",
                title=_t(locale, "switch_port_capacity_title", switch=sw.name, pct=pct),
                description=_t(
                    locale,
                    "switch_port_capacity_desc",
                    switch=sw.name,
                    used=int(agg.in_use),
                    total=int(agg.total),
                ),
                recommendation=_t(locale, "switch_port_capacity_reco"),
                affected_entities=[{"type": "switch", "id": sw.id, "name": sw.name}],
            )
        )
    return issues


# Suppress unused-import warning — Site is imported to keep the SQLAlchemy
# metadata graph eager-resolved when this module is imported standalone.
_ = Site
