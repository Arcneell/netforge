# 04 — REST API

All routes are prefixed with `/api`. JSON only. Auth via session cookie (see [06-auth.md](06-auth.md)).

## Conventions

- **Pagination**: `?page=1&page_size=50` on every list, paginated responses in `{ items, total, page, page_size }`.
- **Filters**: query string, e.g. `/api/ips?subnet_id=12&status=assigned`.
- **Sorting**: `?sort=field` or `?sort=-field` (desc).
- **Errors**: standard format `{ error: { code, message, details } }` with consistent HTTP codes.
- **Validation**: Pydantic handles input validation; 422 responses detail errors per field.
- **Dates**: ISO 8601 UTC.

## Auth

| Method | Path | Description |
|---------|--------|-------------|
| GET | `/api/auth/login` | Redirects to Entra ID (authorization code + PKCE flow) |
| GET | `/api/auth/callback` | OIDC callback, creates/updates user, sets session cookie |
| POST | `/api/auth/logout` | Destroys the session, redirects to Entra ID logout |
| GET | `/api/auth/me` | Returns `{ id, email, display_name, role }` for the current user |

## Sites & rooms

| Method | Path | Description |
|---------|--------|-------------|
| GET | `/api/sites` | List |
| POST | `/api/sites` | Create (admin) |
| GET | `/api/sites/{id}` | Detail + associated rooms |
| PUT | `/api/sites/{id}` | Update (admin) |
| DELETE | `/api/sites/{id}` | Delete if no linked switches/subnets (admin) |
| GET | `/api/rooms` | List, filterable by `site_id` |
| POST | `/api/rooms` | Create (admin) |
| GET | `/api/rooms/{id}` | Detail |
| PUT | `/api/rooms/{id}` | Update (admin) |
| DELETE | `/api/rooms/{id}` | Delete (admin) |

## VLANs

| Method | Path | Description |
|---------|--------|-------------|
| GET | `/api/vlans` | List |
| POST | `/api/vlans` | Create (admin) |
| GET | `/api/vlans/{id}` | Detail + subnets + using ports |
| PUT | `/api/vlans/{id}` | Update (admin) |
| DELETE | `/api/vlans/{id}` | Delete if unused (admin) |

## Subnets

| Method | Path | Description |
|---------|--------|-------------|
| GET | `/api/subnets` | List with stats `{ total, used, free, percent_used }` |
| POST | `/api/subnets` | Create (admin) |
| GET | `/api/subnets/{id}` | Detail |
| GET | `/api/subnets/{id}/ips` | All IPs in the subnet (assigned + computed free) |
| PUT | `/api/subnets/{id}` | Update (admin) |
| DELETE | `/api/subnets/{id}` | Cascading delete of IPs (admin, frontend confirmation) |

Example response for `/api/subnets/{id}/ips`:
```json
{
  "subnet": { "id": 12, "cidr": "10.0.30.0/24", "gateway": "10.0.30.1" },
  "ips": [
    { "address": "10.0.30.1", "status": "reserved", "hostname": "gw-vlan30" },
    { "address": "10.0.30.2", "status": "assigned", "hostname": "srv-ad-01", "mac": "aa:bb:cc:dd:ee:ff" },
    { "address": "10.0.30.3", "status": "free" },
    ...
  ]
}
```

## IPs

| Method | Path | Description |
|---------|--------|-------------|
| GET | `/api/ips` | List, filterable `?subnet_id=&status=&q=` |
| POST | `/api/ips` | Reserve/assign an IP (admin) |
| GET | `/api/ips/{id}` | Detail |
| PUT | `/api/ips/{id}` | Update (admin) |
| DELETE | `/api/ips/{id}` | Release (admin) |
| POST | `/api/subnets/{id}/next-free` | Returns the next free IP in the subnet (utility) |

## Devices

| Method | Path | Description |
|---------|--------|-------------|
| GET | `/api/devices` | List, filterable `?type=&room_id=&q=` |
| POST | `/api/devices` | Create (admin) |
| GET | `/api/devices/{id}` | Detail + IPs + connected ports |
| PUT | `/api/devices/{id}` | Update (admin) |
| DELETE | `/api/devices/{id}` | Delete (admin) — disassociates IPs and ports |

## Switches

| Method | Path | Description |
|---------|--------|-------------|
| GET | `/api/switches` | List |
| POST | `/api/switches` | Create + generate the N ports (admin) |
| GET | `/api/switches/{id}` | Detail with all ports |
| PUT | `/api/switches/{id}` | Update metadata (admin) |
| DELETE | `/api/switches/{id}` | Delete + ports + links (admin, confirmation) |

## Ports

| Method | Path | Description |
|---------|--------|-------------|
| GET | `/api/switches/{switch_id}/ports` | List of ports for the switch |
| GET | `/api/ports/{id}` | Detail |
| PUT | `/api/ports/{id}` | Update (label, VLAN, device, notes) (admin) |
| POST | `/api/ports/{id}/vlans` | Add tagged VLAN to a trunk (admin) |
| DELETE | `/api/ports/{id}/vlans/{vlan_id}` | Remove tagged VLAN (admin) |

## Links (topology)

| Method | Path | Description |
|---------|--------|-------------|
| GET | `/api/links` | List |
| POST | `/api/links` | Create a link between 2 ports (admin) |
| DELETE | `/api/links/{id}` | Delete (admin) |

## Topology

| Method | Path | Description |
|---------|--------|-------------|
| GET | `/api/topology` | Full graph in Cytoscape format: `{ nodes: [...], edges: [...] }` |
| GET | `/api/topology?site_id=3` | Filtered by site |

Example response:
```json
{
  "nodes": [
    { "data": { "id": "sw-1", "label": "SW-SRV-01", "type": "switch", "ports_count": 48 } },
    { "data": { "id": "sw-2", "label": "SW-ETAGE-01", "type": "switch", "ports_count": 24 } }
  ],
  "edges": [
    { "data": { "id": "l-1", "source": "sw-1", "target": "sw-2", "speed": "10G", "type": "fiber" } }
  ]
}
```

## Global search

| Method | Path | Description |
|---------|--------|-------------|
| GET | `/api/search?q=...` | Search across IP, hostname, MAC, switch name, port label, device name |

Response:
```json
{
  "results": [
    { "type": "ip", "id": 3421, "label": "10.0.30.47", "context": "srv-ad-01 (VLAN 30)" },
    { "type": "device", "id": 88, "label": "srv-ad-01", "context": "Site HQ / SRV-01 Room" },
    { "type": "port", "id": 712, "label": "SW-SRV-01 / port 14", "context": "Accounting office 3" }
  ]
}
```

## CSV import / export

| Method | Path | Description |
|---------|--------|-------------|
| POST | `/api/imports/{entity}` | Multipart CSV upload. `entity` ∈ `subnets`, `vlans`, `ips`, `switches`, `ports`, `devices`, `links` |
| GET | `/api/exports/{entity}` | CSV stream |

See [08-import-csv.md](08-import-csv.md) for the expected formats.

## Audit log

| Method | Path | Description |
|---------|--------|-------------|
| GET | `/api/audit` | Paginated list, filters `?entity=&entity_id=&user_id=&from=&to=` |
| GET | `/api/audit/{id}` | Before/after detail (JSON diff) |

Only `admin` users can view the full log. `viewer` users only see their own actions (none in practice given their role).

## Error codes

| Code | Meaning |
|------|---------------|
| `AUTH_REQUIRED` | 401 — no valid session |
| `FORBIDDEN` | 403 — insufficient role |
| `NOT_FOUND` | 404 — entity does not exist |
| `VALIDATION_ERROR` | 422 — invalid payload, per-field details |
| `CONFLICT` | 409 — e.g. overlapping subnet, MAC already used |
| `BUSINESS_RULE` | 400 — e.g. IP outside subnet, link on nonexistent port |
| `RATE_LIMITED` | 429 — login bruteforce (rate limit on `/auth/login`) |
| `INTERNAL_ERROR` | 500 — catch-all, logged server-side with a `trace_id` returned to the client |

## OpenAPI

FastAPI automatically exposes `/api/docs` (Swagger) and `/api/redoc`. In production these routes are either protected behind admin auth or disabled depending on config.
