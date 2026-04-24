# 01 — Vision

## Why Netforge

In many organizations, the network infrastructure is documented in Excel files, sticky notes, scattered notes, and the memory of the admins. When a problem hits ("the phone in the accounting office stopped working"), someone has to dig around to find:

- which switch serves that office,
- which port the cable is plugged into,
- which VLAN is configured,
- which IP is assigned,
- who else is in that subnet.

Netforge centralizes all of this in a single web interface, with a graph view for visual diagnostics.

## Goals

1. **Single source of truth** for IP addressing and switch topology.
2. **Fast diagnostics**: find the device plugged into a given port in under 10 seconds.
3. **Planning**: see free IPs in a subnet before assigning a new one.
4. **Mapping**: visualize inter-switch links to understand network paths.
5. **Traceability**: who changed what, when, why (audit log).

## Target audience

- **Network administrator / sysadmin**: data entry, day-to-day consultation, diagnostics.
- **Wider technical team** (support, occasional contractors): read-only access.
- **Outsiders**: none. The tool is designed for an internal deployment, protected by SSO authentication.

## v1 scope (MVP)

### Included
- Management of **subnets** (IPv4, CIDR, gateway, associated VLAN, description).
- Management of **VLANs** (ID, name, description, associated subnets).
- Management of **IPs** within a subnet (reserved, assigned, free) with hostname, MAC, linked device.
- Management of **switches** (model, location, management IP, port count).
- Management of **ports** per switch (number, label, access/trunk VLAN, state, connected device).
- Management of **links** between switches (uplink/downlink) to compute topology.
- **Topology view** rendered with Cytoscape.js (drag, zoom, click on a node → details).
- **CSV import** per entity type (quick bootstrap from existing Excel files).
- **CSV export** for every table (backup / sharing outside the tool).
- **Entra ID auth** multi-user, 2 roles: `viewer` (read) and `admin` (write).
- **Audit log**: every change is tracked (who, when, before → after).
- **Global search**: a search bar that looks across IP, hostname, MAC, switch name, port label.

### Excluded from v1
- SNMP auto-discovery of switches (v2 scope).
- Zabbix integration (v2 scope).
- Provisioning (pushing config to switches) — never, too risky.
- IPv6 — v1 targets fully IPv4 networks; IPv6 support will come later.
- Multi-tenant — a single network.
- Public / external API — the API exists but is not exposed.

## v2 scope (after MVP validation)

- **SNMP polling**: periodic scan of Aruba switches to automatically populate port/MAC/VLAN tables.
- **Zabbix sync**: read the Zabbix inventory to enrich device records.
- **Extended device inventory**: servers, printers, APs, Fanvil phones with a full record (model, serial, support contract).
- **Alerts**: Telegram notification if a port goes down, if a subnet approaches saturation (> 90% used).

## Permanently out of scope

- **Pushing config** to switches: risk is too high — we stay read-only.
- **Built-in DHCP server**: we assume an external DHCP is already in place (Windows, ISC, Kea, etc.) and we do not reimplement it.
- **DNS management**: same — AD DNS is enough.
- **Billing / TCO**: this is not a commercial CMDB.

## Success metrics

- Network incident diagnostic time divided by 3 vs today (subjective benchmark).
- 100% of production subnets and VLANs entered within 2 weeks after go-live.
- All server room switches + floor switches documented port by port.
- Zero incidents caused by lack of network visibility over 6 months post-v1.
