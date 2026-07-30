# 04 — REST API

All routes are prefixed with `/api`. JSON only. Auth via session cookie or `Authorization: Bearer` personal access token (see [06-auth.md](06-auth.md)).

## Conventions

- **Pagination**: `?page=1&page_size=50` on every list, paginated responses in `{ items, total, page, page_size }`.
- **Filters**: query string, e.g. `/api/ips?subnet_id=12&status=assigned`.
- **Sorting**: `?sort=field` or `?sort=-field` (desc).
- **Errors**: standard format `{ error: { code, message, details } }` with consistent HTTP codes.
- **Validation**: Pydantic handles input validation; 422 responses detail errors per field.
- **Dates**: ISO 8601 UTC.

## Auth

Auth is **pluggable** — `AUTH_PROVIDER` picks `github`, `oidc` (any IdP with
`.well-known/openid-configuration`: Entra ID, Keycloak, Authentik, Google
Workspace, …) or `dev`. See [06-auth.md](06-auth.md) for the full flow,
provider setup, and personal access tokens.

| Method | Path | Description |
|---------|--------|-------------|
| GET | `/api/auth/login` | Redirects to the configured IdP's authorize endpoint |
| GET | `/api/auth/callback` | Provider callback, creates/updates user (JIT), sets session cookie |
| POST | `/api/auth/logout` | Destroys the session |
| GET | `/api/auth/me` | Returns `{ id, email, display_name, role }` for the current user |
| GET | `/api/auth/tokens` | List the caller's personal access tokens |
| POST | `/api/auth/tokens` | Mint a new token — plaintext returned once |
| DELETE | `/api/auth/tokens/{id}` | Revoke a token |

The API is not anonymous, but it isn't cookie-only either: every route also
accepts `Authorization: Bearer nfp_...` (a personal access token) in place of
the session cookie — see [06-auth.md](06-auth.md#personal-access-tokens-api)
for the full contract.

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

## VRFs

Routing-table isolation for overlapping CIDRs (see [03-data-model.md](03-data-model.md)). A subnet's `vrf_id` is `null` for the global scope.

| Method | Path | Description |
|---------|--------|-------------|
| GET | `/api/vrfs` | List |
| POST | `/api/vrfs` | Create (admin) |
| GET | `/api/vrfs/{id}` | Detail |
| PUT | `/api/vrfs/{id}` | Update (admin) |
| DELETE | `/api/vrfs/{id}` | Delete (admin) |

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
| GET | `/api/links/{id}` | Read one link |
| POST | `/api/links` | Create a link between 2 ports, identified by numeric port ids (admin) |
| POST | `/api/links/by-name` | Create a link by `(switch_name, port_number)` for both endpoints (admin) |
| PUT | `/api/links/{id}` | Patch metadata only: `link_type`, `speed_mbps`, `description` (admin). Endpoints are immutable here — to change connected ports, delete and recreate. |
| DELETE | `/api/links/{id}` | Delete (admin) |

## Cables

Physical cable inventory, one-to-one with a `Link` via `link_id` (`null` = in stock, not patched). See [03-data-model.md](03-data-model.md).

| Method | Path | Description |
|---------|--------|-------------|
| GET | `/api/cables` | List, `?in_stock=true` filters to unpatched cables |
| POST | `/api/cables` | Create (admin) |
| GET | `/api/cables/{id}` | Detail |
| PUT | `/api/cables/{id}` | Update (admin) |
| DELETE | `/api/cables/{id}` | Delete (admin) |
| GET | `/api/links/{id}/cable` | The cable attached to a link, 404 if none recorded yet |

## Topology

| Method | Path | Description |
|---------|--------|-------------|
| GET | `/api/topology` | Graph in Cytoscape element format: `{ nodes, edges, stats, truncated }` |

Query parameters, all optional:

| Parameter | Effect |
|---|---|
| `site_id` | Restrict to switches and devices in this site |
| `room_id` | Restrict to a single room |
| `vlan_id` | Keep only switches carrying this VLAN (native or tagged) on at least one port. Every link **between** those switches is still returned — filtering edges too would hide the cable that actually carries the VLAN |
| `include_devices` | Default `true`. Set `false` for a switch-only backbone view |

Four node kinds share one payload. `site` and `room` are compound *group*
nodes; `switch` and `device` are leaves that name their room in `parent`, so
Cytoscape draws the grouping without the client rebuilding the hierarchy.
`id` is prefixed because element ids share one namespace across four tables;
`entity_id` carries the un-prefixed PK for navigation.

Two edge kinds: `link` for a physical cable between two switch ports, and
`attachment` for a device plugged into a port (`ports.connected_device_id`).
Only `link` edges carry `link_type` / `speed_mbps` / `port_b`.

Group nodes are emitted only for rooms that hold something, and for sites
holding such a room. Both the switch and link queries are capped at the DB
level; `truncated` says the payload was cut down. `stats` is computed from
the returned payload, so it always describes exactly what the caller got.

Example response:
```json
{
  "nodes": [
    { "data": { "id": "site-3", "label": "PAR", "kind": "site", "entity_id": 3, "child_count": 1 } },
    { "data": { "id": "room-7", "label": "MDF", "kind": "room", "entity_id": 7, "parent": "site-3", "child_count": 2 } },
    { "data": { "id": "sw-1", "label": "SW-SRV-01", "kind": "switch", "entity_id": 1, "parent": "room-7", "ports_total": 48, "ports_used": 12 } },
    { "data": { "id": "dev-42", "label": "srv-ad-01", "kind": "device", "entity_id": 42, "parent": "room-7", "device_type": "server" } }
  ],
  "edges": [
    { "data": { "id": "link-1", "kind": "link", "source": "sw-1", "target": "sw-2", "link_type": "fiber", "speed_mbps": 10000, "port_a": 49, "port_b": 24 } },
    { "data": { "id": "attach-88", "kind": "attachment", "source": "sw-1", "target": "dev-42", "port_a": 5 } }
  ],
  "stats": { "sites": 1, "rooms": 1, "switches": 2, "devices": 1, "links": 1, "attachments": 1, "isolated_switches": 0, "unplaced_nodes": 0, "link_types": { "fiber": 1 } },
  "truncated": false
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
| POST | `/api/imports/detect` | Header-row inspection — returns the most likely entity for a CSV |
| POST | `/api/imports/bulk` | Multi-file or `.zip` upload, auto-routed and applied in dependency order inside one transaction |
| GET | `/api/exports/{entity}` | CSV stream |
| GET | `/api/exports/all` | ZIP archive containing every entity's CSV — round-trip-compatible with `POST /api/imports/bulk` |
| GET | `/api/exports/audit` | Audit log as CSV (admin). Same filters as `GET /api/audit`: `entity`, `entity_id`, `user_id`, `from`, `to` |

See [08-import-csv.md](08-import-csv.md) for the expected formats.

## Audit log

| Method | Path | Description |
|---------|--------|-------------|
| GET | `/api/audit` | Paginated list, filters `?entity=&entity_id=&user_id=&from=&to=` |
| GET | `/api/audit/{id}` | Before/after detail (JSON diff) |

Only `admin` users can view the full log. `viewer` users only see their own actions (none in practice given their role).

## Webhooks (admin-only)

Outbound HTTP subscribers, fired for every audited mutation (`{entity}.{action}`, e.g. `port.update`). Payloads are signed HMAC-SHA256 (`X-Netforge-Signature`) with a secret shown once at creation / rotation. See `backend/app/models/webhook.py`.

| Method | Path | Description |
|---------|--------|-------------|
| GET | `/api/webhooks` | List (secrets never included) |
| POST | `/api/webhooks` | Create — response includes the plaintext secret once |
| GET | `/api/webhooks/{id}` | Detail |
| PATCH | `/api/webhooks/{id}` | Update name / url / events / enabled |
| DELETE | `/api/webhooks/{id}` | Delete |
| POST | `/api/webhooks/{id}/rotate-secret` | Rotate the signing secret — new plaintext returned once |
| POST | `/api/webhooks/{id}/test` | Send a synthetic test event, records a delivery |
| GET | `/api/webhooks/{id}/deliveries` | Recent delivery attempts (status, latency, error) |

## AI features (optional)

Gated behind `AI_PROVIDER` (`anthropic` / `openai` / `gemini` / unset = disabled) — routes 501 when disabled. Covers natural-language querying, an infrastructure advisor (insights + link suggestions), CSV column-mapping assistance, PDF export of the advisor report, and scheduled scans. See `backend/app/routers/ai/` (`query.py`, `insights.py`, `suggestions.py`, `drafts.py`, `csv_mapping.py`, `conversations.py`, `schedules.py`, `pdf_export.py`, `status.py`, `usage.py`, `integrity.py`, `streaming.py`) for the full surface — all mounted under `/api/ai`.

## Error codes

| Code | Meaning |
|------|---------------|
| `AUTH_REQUIRED` | 401 — no valid session |
| `FORBIDDEN` | 403 — insufficient role |
| `NOT_FOUND` | 404 — entity does not exist |
| `VALIDATION_ERROR` | 422 — invalid payload, per-field details |
| `CONFLICT` | 409 — e.g. overlapping subnet, MAC already used |
| `BUSINESS_RULE` | 400 — e.g. IP outside subnet, link on nonexistent port |
| `RATE_LIMITED` | 429 — per-IP limit on write methods, expensive export GETs, and `/auth/login`/`/auth/callback` |
| `AI_RATE_LIMITED` | 429 — the AI provider itself rate-limited the request (not our own limiter) |
| `INTERNAL_ERROR` | 500 — catch-all, logged server-side with a `trace_id` returned to the client |

## OpenAPI

FastAPI automatically exposes `/api/docs` (Swagger) and `/api/redoc`. In production these routes are either protected behind admin auth or disabled depending on config.
