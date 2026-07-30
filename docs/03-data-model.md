# 03 — Data model

The schema uses PostgreSQL 16. The `INET`, `CIDR` and `MACADDR` types are native — we do not store them as `VARCHAR`.

## ER diagram (summary)

```
sites (1) ──< (N) rooms (1) ──< (N) switches (1) ──< (N) ports
                                     │                      │
                                     │                      ├─< links (switch-to-switch) ──1:1── cables
                                     │
vrfs (1) ──< (N) subnets (self-referencing parent_subnet_id)
                                     │
vlans (N) ──< vlan_subnet >── (N) subnets (1) ──< (N) ips
                                     │                      │
                                     │                      └──> devices (optional FK)
                                     │
                                     └──> vlan per port (access/trunk) via `port_vlan` table

users (1) ──< sessions, api_tokens        webhooks ──< webhook_deliveries
users, audit_log (cross-cutting)
```

## Tables in detail

### `sites`
Physical sites (branch offices, headquarters, datacenters).

| Column | Type | Constraint | Description |
|---------|------|-----------|-------------|
| id | serial | PK | |
| code | varchar(20) | UNIQUE NOT NULL | Short code, e.g. `PAR`, `LYON` |
| name | varchar(200) | NOT NULL | Full name, e.g. `Paris HQ` |
| address | text | | Postal address |
| created_at | timestamptz | DEFAULT now() | |
| updated_at | timestamptz | DEFAULT now() | |

### `rooms`
Rooms / technical rooms / racks within a site.

| Column | Type | Constraint | Description |
|---------|------|-----------|-------------|
| id | serial | PK | |
| site_id | int | FK → sites(id) ON DELETE RESTRICT | |
| code | varchar(50) | NOT NULL | e.g. `SALLE-SRV-01`, `BAIE-A` |
| description | text | | |
| UNIQUE (site_id, code) | | | |

### `vlans`
Network VLANs.

| Column | Type | Constraint | Description |
|---------|------|-----------|-------------|
| id | serial | PK | |
| vlan_id | int | UNIQUE NOT NULL CHECK (vlan_id BETWEEN 1 AND 4094) | |
| name | varchar(100) | NOT NULL | e.g. `VLAN-USERS`, `VLAN-VOIP` |
| description | text | | |
| color | varchar(7) | | Hex `#RRGGBB` for display |

### `subnets`
IPv4 subnets.

| Column | Type | Constraint | Description |
|---------|------|-----------|-------------|
| id | serial | PK | |
| cidr | cidr | NOT NULL | e.g. `10.0.30.0/24` |
| gateway | inet | | Gateway |
| vlan_id | int | FK → vlans(id) ON DELETE SET NULL | The subnet's primary VLAN |
| site_id | int | FK → sites(id) ON DELETE RESTRICT | |
| vrf_id | int | FK → vrfs(id) ON DELETE RESTRICT | `NULL` = global scope, see `vrfs` below |
| parent_subnet_id | int | FK → subnets(id) ON DELETE SET NULL | Optional hierarchical IPAM parent |
| description | text | | |
| dhcp_enabled | bool | DEFAULT false | Informational (DHCP managed by Windows) |
| dhcp_range_start | inet | | |
| dhcp_range_end | inet | | |
| created_at | timestamptz | DEFAULT now() | |
| updated_at | timestamptz | DEFAULT now() | |

**Key constraint** — no overlap, partitioned by VRF scope (two GiST exclusions — global scope and per-`vrf_id` — plus a trigger that checks a child subnet against its siblings under the same `parent_subnet_id`, since `&&` alone can't distinguish "overlap" from "legitimate containment"):
```sql
ALTER TABLE subnets ADD CONSTRAINT subnets_no_overlap_global
  EXCLUDE USING gist (cidr inet_ops WITH &&) WHERE (vrf_id IS NULL);
ALTER TABLE subnets ADD CONSTRAINT subnets_no_overlap_vrf
  EXCLUDE USING gist (vrf_id WITH =, cidr inet_ops WITH &&) WHERE (vrf_id IS NOT NULL);
```

### `ips`
Individual IP addresses (reserved, assigned).

| Column | Type | Constraint | Description |
|---------|------|-----------|-------------|
| id | serial | PK | |
| subnet_id | int | FK → subnets(id) ON DELETE CASCADE | |
| address | inet | NOT NULL UNIQUE | |
| hostname | varchar(255) | | FQDN or short name |
| mac | macaddr | | MAC if known |
| device_id | int | FK → devices(id) ON DELETE SET NULL | |
| status | enum | NOT NULL | `reserved`, `assigned`, `dhcp` |
| description | text | | |
| created_at | timestamptz | DEFAULT now() | |
| updated_at | timestamptz | DEFAULT now() | |

**Business rule constraint** (trigger or CHECK):
```sql
-- address must be contained in the subnet identified by subnet_id
CREATE FUNCTION check_ip_in_subnet() RETURNS trigger AS $$
BEGIN
  IF NEW.address <<= (SELECT cidr FROM subnets WHERE id = NEW.subnet_id) THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'IP % not in subnet', NEW.address;
END;
$$ LANGUAGE plpgsql;
```

### `devices`
Physical or virtual devices that carry an IP or are plugged into a port.

| Column | Type | Constraint | Description |
|---------|------|-----------|-------------|
| id | serial | PK | |
| name | varchar(255) | NOT NULL | Primary hostname |
| type | enum | NOT NULL | `server`, `desktop`, `laptop`, `printer`, `phone`, `ap`, `camera`, `ups`, `other` |
| vendor | varchar(100) | | `HP`, `Lenovo`, `Fanvil`, `Aruba`... |
| model | varchar(100) | | |
| serial | varchar(100) | | |
| room_id | int | FK → rooms(id) ON DELETE SET NULL | |
| description | text | | |

### `switches`
Switches specifically — conceptually inherits from `devices` but kept as a separate table because of the specific fields.

| Column | Type | Constraint | Description |
|---------|------|-----------|-------------|
| id | serial | PK | |
| name | varchar(100) | UNIQUE NOT NULL | e.g. `SW-SRV-01` |
| vendor | varchar(50) | | `Aruba`, `HP`, `Cisco` |
| model | varchar(100) | | e.g. `Aruba 2930F-48G` |
| serial | varchar(100) | | |
| management_ip | inet | | Management IP |
| room_id | int | FK → rooms(id) ON DELETE RESTRICT | |
| rack_position | varchar(20) | | e.g. `U12` |
| port_count | int | NOT NULL CHECK (port_count > 0) | Total number of ports |
| firmware_version | varchar(50) | | |
| snmp_community | varchar(100) | | Encrypted at rest (pgcrypto) — for v2 |
| description | text | | |
| created_at | timestamptz | DEFAULT now() | |
| updated_at | timestamptz | DEFAULT now() | |

### `ports`
Switch ports. Created automatically when the switch is created (trigger or service).

| Column | Type | Constraint | Description |
|---------|------|-----------|-------------|
| id | serial | PK | |
| switch_id | int | FK → switches(id) ON DELETE CASCADE | |
| number | int | NOT NULL | Port number (1, 2, ...) |
| label | varchar(100) | | Free-form label, e.g. `Accounting office 3` |
| mode | enum | NOT NULL DEFAULT 'access' | `access`, `trunk`, `hybrid`, `disabled` |
| native_vlan_id | int | FK → vlans(id) ON DELETE SET NULL | Native VLAN for access, native for trunk |
| admin_status | enum | NOT NULL DEFAULT 'up' | `up`, `down` |
| connected_device_id | int | FK → devices(id) ON DELETE SET NULL | Connected device |
| connected_ip_id | int | FK → ips(id) ON DELETE SET NULL | IP seen on this port (if known) |
| notes | text | | |
| UNIQUE (switch_id, number) | | | |

### `port_vlan`
Join table for ports in `trunk` mode — list of tagged VLANs.

| Column | Type | Constraint | Description |
|---------|------|-----------|-------------|
| port_id | int | FK → ports(id) ON DELETE CASCADE | |
| vlan_id | int | FK → vlans(id) ON DELETE CASCADE | |
| PRIMARY KEY (port_id, vlan_id) | | | |

### `links`
Links between two switch ports (uplinks, cascades).

| Column | Type | Constraint | Description |
|---------|------|-----------|-------------|
| id | serial | PK | |
| port_a_id | int | FK → ports(id) ON DELETE CASCADE NOT NULL | |
| port_b_id | int | FK → ports(id) ON DELETE CASCADE NOT NULL | |
| link_type | enum | NOT NULL | `copper`, `fiber`, `dac`, `virtual` |
| speed_mbps | int | | `1000`, `10000`... |
| description | text | | |
| CHECK (port_a_id <> port_b_id) | | | |
| UNIQUE (port_a_id, port_b_id) | | | |

**Symmetry**: we store `(a, b)` with `a < b` to avoid reversed duplicates (enforced via trigger or service).

### `vrfs`
Routing-table isolation units — two subnets in different VRFs may share an overlapping CIDR. `NULL` `vrf_id` on a subnet means the global scope. See [04-api.md](04-api.md#vrfs).

| Column | Type | Constraint | Description |
|---------|------|-----------|-------------|
| id | serial | PK | |
| name | varchar(64) | UNIQUE NOT NULL | e.g. `tenant-a`, `prod` |
| rd | varchar(32) | UNIQUE | Route distinguisher (BGP/MPLS sense), optional |
| description | text | | |

`subnets.vrf_id` → FK `vrfs(id) ON DELETE RESTRICT` (nullable — `NULL` = global scope). The no-overlap GiST exclusion on `subnets.cidr` is partitioned by `vrf_id` so two VRFs can reuse the same address space.

### `cables`
Physical cable inventory — metadata bag for the cable that realises a `link`, kept separate from `links` because a cable outlives any one link (re-patching swaps which link it realises) and can exist before it's plugged in anywhere.

| Column | Type | Constraint | Description |
|---------|------|-----------|-------------|
| id | serial | PK | |
| label | varchar(120) | | Printed label, e.g. `PA-CR12-A03` |
| link_id | int | FK → links(id) ON DELETE SET NULL, UNIQUE | `NULL` = in stock, not patched |
| length_m | int | | |
| color | varchar(40) | | |
| vendor | varchar(100) | | |
| part_number | varchar(100) | | |
| serial | varchar(120) | | |
| installed_on | date | | |
| last_tested_on | date | | |
| notes | text | | |

### `users`
Netforge users, provisioned on first login (JIT) through whichever `AUTH_PROVIDER` is configured (GitHub OAuth, generic OIDC — Entra ID / Keycloak / Authentik / …, or `dev`). See [06-auth.md](06-auth.md).

| Column | Type | Constraint | Description |
|---------|------|-----------|-------------|
| id | serial | PK | |
| provider | varchar(32) | NOT NULL, UNIQUE with `subject` | `"github"`, `"oidc"`, ... — see `app/auth/factory.py` |
| subject | varchar(255) | NOT NULL, UNIQUE with `provider` | Opaque id from the provider (GitHub numeric id, OIDC `sub` claim) |
| email | varchar(255) | NOT NULL | |
| display_name | varchar(255) | | |
| role | enum | NOT NULL DEFAULT 'viewer' | `viewer`, `admin` |
| last_login_at | timestamptz | | |
| created_at | timestamptz | DEFAULT now() | |

### `sessions`
DB-backed session store (no JWT exposed to the client — see [06-auth.md](06-auth.md)).

| Column | Type | Constraint | Description |
|---------|------|-----------|-------------|
| id | varchar(64) | PK | SHA-256 digest of the opaque cookie token |
| user_id | int | FK → users(id) ON DELETE CASCADE | |
| created_at | timestamptz | DEFAULT now() | |
| expires_at | timestamptz | NOT NULL | Sliding renewal on active use |
| ip_address | inet | | |
| user_agent | text | | |

### `api_tokens`
Personal access tokens (`Authorization: Bearer nfp_...`) for scripts/CI — see [06-auth.md](06-auth.md#personal-access-tokens-api). Only the SHA-256 digest is stored; the plaintext is shown once at creation.

| Column | Type | Constraint | Description |
|---------|------|-----------|-------------|
| id | serial | PK | |
| user_id | int | FK → users(id) ON DELETE CASCADE | Token inherits the owner's role |
| name | varchar(100) | NOT NULL | Operator-chosen label |
| token_hash | varchar(64) | UNIQUE NOT NULL | SHA-256 digest of the plaintext |
| prefix | varchar(16) | NOT NULL | First ~8 chars in clear, for recognition in the list |
| created_at | timestamptz | DEFAULT now() | |
| expires_at | timestamptz | | `NULL` = never expires |
| last_used_at | timestamptz | | |
| revoked_at | timestamptz | | Soft-delete; an active token has this `NULL` |

### `webhooks` / `webhook_deliveries`
Operator-defined HTTP subscribers fired on every audited mutation. See [04-api.md](04-api.md#webhooks-admin-only).

| Column (`webhooks`) | Type | Constraint | Description |
|---------|------|-----------|-------------|
| id | serial | PK | |
| name | varchar(100) | UNIQUE NOT NULL | |
| url | varchar(500) | NOT NULL | |
| secret | varchar(64) | NOT NULL | HMAC-SHA256 signing key, shown once |
| events | jsonb | NOT NULL | Pattern list, e.g. `["port.*", "site.create"]` |
| enabled | bool | DEFAULT true | |
| total_deliveries / total_failures | int | DEFAULT 0 | Aggregate counters |
| last_delivery_at / last_status_code / last_error | | | |

`webhook_deliveries(webhook_id FK CASCADE, event, payload jsonb, status_code, success, error, latency_ms, created_at)` — one row per attempt, trimmed after 30 days.

### `audit_log`
Full trace of writes.

| Column | Type | Constraint | Description |
|---------|------|-----------|-------------|
| id | bigserial | PK | |
| user_id | int | FK → users(id) ON DELETE SET NULL | |
| action | enum | NOT NULL | `create`, `update`, `delete` |
| entity | varchar(50) | NOT NULL | `subnet`, `ip`, `switch`, `port`... |
| entity_id | int | | |
| changes | jsonb | | `{ "before": {...}, "after": {...} }` |
| ip_address | inet | | Source IP of the request |
| user_agent | text | | |
| created_at | timestamptz | DEFAULT now() NOT NULL | |

**Indexes**: `(entity, entity_id)`, `(user_id)`, `(created_at DESC)`.

## Summary of critical relationships

- `subnet.vlan_id` → a subnet has 0 or 1 "primary" VLAN.
- `port.native_vlan_id` → a port has 0 or 1 native/access VLAN.
- `port_vlan` → a trunk port has N tagged VLANs.
- `ip.device_id` → an IP points to 0 or 1 device.
- `port.connected_device_id` → a port sees 0 or 1 device.
- A device can have several IPs (via `ips.device_id`) and be plugged into several ports (rare but possible — LAG).

## Migrations

All schema changes go through **Alembic**. Migrations are versioned under `backend/alembic/versions/` and numbered. No manual changes in production.

The initial migration `0001_initial.py` creates every table above, the GiST constraints and the triggers. A fresh install starts with an empty database — populate it via the bulk CSV import (`POST /api/imports/bulk`) or the CRUD UI.
