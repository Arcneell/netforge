# 08 — CSV import / export

CSV import is **the** preferred path to bootstrap Netforge from existing Excel files. One file per entity type. Separator `;` (Excel FR-compatible), encoding `UTF-8 BOM`.

## Common rules

- First line = headers, respect the case.
- Columns marked *required* must be filled in.
- Columns marked *reference* (e.g. `site_code`, `vlan_id`) perform a lookup on the existing entity — if not found, the import fails for that row.
- Import mode is configurable: **create_only**, **update_only**, **upsert** (key determined per entity, see tables).
- Dry-run available: the backend parses, validates, returns the report without writing.

## Formats

### Sites (`sites.csv`)

| Column | Required | Example | Comment |
|---------|-------------|---------|-------------|
| code | yes | `PAR` | Upsert key |
| name | yes | `Paris HQ` | |
| address | no | `12 rue X, 75001 Paris` | |

### Rooms (`rooms.csv`)

| Column | Required | Example | Comment |
|---------|-------------|---------|-------------|
| site_code | yes (ref) | `PAR` | Must exist |
| code | yes | `SALLE-SRV-01` | Upsert key together with `site_code` |
| description | no | `Rack A, U1-U42` | |

### VLANs (`vlans.csv`)

| Column | Required | Example | Comment |
|---------|-------------|---------|-------------|
| vlan_id | yes | `30` | Upsert key, 1-4094 |
| name | yes | `VLAN-VOIP` | |
| description | no | `Fanvil telephony` | |
| color | no | `#F97316` | Hex |

### Subnets (`subnets.csv`)

| Column | Required | Example | Comment |
|---------|-------------|---------|-------------|
| cidr | yes | `10.0.30.0/24` | Upsert key |
| gateway | no | `10.0.30.1` | Must be within the CIDR |
| vlan_id | no (ref) | `30` | VLAN number |
| site_code | yes (ref) | `PAR` | |
| description | no | `Floor 1 telephony` | |
| dhcp_enabled | no | `true` | bool |
| dhcp_range_start | no | `10.0.30.50` | |
| dhcp_range_end | no | `10.0.30.200` | |

### IPs (`ips.csv`)

| Column | Required | Example | Comment |
|---------|-------------|---------|-------------|
| address | yes | `10.0.30.47` | Upsert key |
| status | yes | `assigned` | `reserved`, `assigned`, `dhcp` |
| hostname | no | `fanvil-accueil-01` | |
| mac | no | `aa:bb:cc:dd:ee:ff` | Accepted formats: `aa:bb:...`, `aa-bb-...`, `aabb.ccdd...` |
| device_name | no (ref) | `fanvil-accueil-01` | If provided, lookup on `devices.name`; created if missing and `auto_create_device=true` |
| description | no | `Fanvil X3U phone reception` | |

Note: `subnet_id` is derived automatically from the IP (it looks up the subnet containing the address).

### Devices (`devices.csv`)

| Column | Required | Example | Comment |
|---------|-------------|---------|-------------|
| name | yes | `srv-ad-01` | Upsert key |
| type | yes | `server` | enum |
| vendor | no | `Dell` | |
| model | no | `PowerEdge R640` | |
| serial | no | `7X8Y9Z0` | |
| site_code | no (ref) | `PAR` | |
| room_code | no (ref) | `SALLE-SRV-01` | |
| description | no | `Primary domain controller` | |

### Switches (`switches.csv`)

| Column | Required | Example | Comment |
|---------|-------------|---------|-------------|
| name | yes | `SW-SRV-01` | Upsert key |
| vendor | no | `Aruba` | |
| model | no | `2930F-48G` | |
| serial | no | `CN12AB3DEF` | |
| management_ip | no | `10.0.10.251` | |
| site_code | yes (ref) | `PAR` | |
| room_code | yes (ref) | `SALLE-SRV-01` | |
| rack_position | no | `U12` | |
| port_count | yes | `48` | On creation, generates N ports |
| firmware_version | no | `WC.16.10.0023` | |

**Important**: if a switch is **created**, ports 1..N are auto-generated empty. If the switch already exists (upsert), `port_count` cannot be reduced without explicit confirmation.

### Ports (`ports.csv`)

| Column | Required | Example | Comment |
|---------|-------------|---------|-------------|
| switch_name | yes (ref) | `SW-SRV-01` | |
| number | yes | `14` | Upsert key together with `switch_name` |
| label | no | `Accounting office 3` | |
| mode | no | `access` | `access`, `trunk`, `hybrid`, `disabled` — default `access` |
| native_vlan | no (ref) | `30` | VLAN number |
| trunk_vlans | no | `10,20,30` | Comma-separated list |
| admin_status | no | `up` | default `up` |
| device_name | no (ref) | `fanvil-accueil-01` | Connected device |
| connected_ip | no | `10.0.30.47` | IP seen on this port |
| notes | no | `Blue cable B14` | |

### Links (`links.csv`)

| Column | Required | Example | Comment |
|---------|-------------|---------|-------------|
| switch_a | yes (ref) | `SW-SRV-01` | |
| port_a | yes | `48` | |
| switch_b | yes (ref) | `SW-ETAGE-01` | |
| port_b | yes | `24` | |
| link_type | no | `fiber` | `copper`, `fiber`, `dac`, `virtual` — default `copper` |
| speed_mbps | no | `10000` | |
| description | no | `Floor 1 uplink` | |

## Behavior

### Upsert
- Upsert key (column or combination) is spelled out in each table.
- If the entity exists → update the provided columns (empty columns = untouched).
- If it does not exist → create.

### Errors
- The backend parses the entire file and applies the mutations in a single **transaction**.
- On any error, **full rollback** and a detailed row-by-row report is returned.
- Report:
```json
{
  "parsed_rows": 124,
  "ok_rows": 120,
  "error_rows": [
    { "line": 17, "column": "vlan_id", "value": "999", "error": "VLAN 999 not found" },
    { "line": 23, "column": "address", "value": "10.0.99.5", "error": "No subnet contains this IP" }
  ],
  "applied": false  // true if dry_run=false and no error
}
```

### Recommended import order

For a from-scratch install, import in this order (dependencies):

1. `sites.csv`
2. `rooms.csv`
3. `vlans.csv`
4. `subnets.csv`
5. `devices.csv`
6. `switches.csv`
7. `ports.csv`
8. `ips.csv` (after devices for the `device_name` lookup)
9. `links.csv`

## Export

`GET /api/exports/{entity}?format=csv` returns a file in the same format as the import. It enables clean round-trips (export → edit in Excel → re-import as upsert).

For admins, a `GET /api/exports/all` endpoint produces a zip containing every table — serves as a logical backup complementary to `pg_dump`.
