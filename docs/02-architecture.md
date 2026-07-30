# 02 — Architecture

## Overview

Netforge follows a classic 3-tier architecture, containerized as Docker services
orchestrated by `docker compose`. Three of them are the tiers; a fourth, `redis`,
is a cache the stack runs fine without.

```
┌─────────────────────────────────────────────────────────────┐
│                    User (browser)                            │
└───────────────────────────────┬─────────────────────────────┘
                                │ HTTPS (Nginx reverse proxy)
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                  nginx container (frontend)                  │
│  - Serves the static Vue 3 build (dist/)                     │
│  - Proxies /api/* → backend                                  │
│  - Applies CSP, HSTS, X-Frame-Options headers                │
└───────────────────────────────┬─────────────────────────────┘
                                │ internal HTTP (docker network)
                                ▼
┌─────────────────────────────────────────────────────────────┐
│              backend container (FastAPI + Uvicorn)           │
│  - REST routes /api/*                                        │
│  - Auth middleware (pluggable OIDC/GitHub/dev, sessions       │
│    + Bearer personal access tokens)                          │
│  - Business logic (services/)                                │
│  - SQLAlchemy 2.0 async ORM                                  │
│  - Alembic migrations                                        │
└──────────────┬──────────────────────────────┬───────────────┘
               │ TCP 5432                     │ TCP 6379
               ▼                              ▼
┌──────────────────────────────┐ ┌──────────────────────────────┐
│      postgres:16 container   │ │      redis:8 container       │
│  - Volume /var/lib/postgre…  │ │  - OPTIONAL (REDIS_URL)      │
│  - System of record          │ │  - Session + read cache      │
│  - Daily backup to Veeam     │ │  - Shared rate-limit counters│
└──────────────────────────────┘ └──────────────────────────────┘
```

## Services

### `frontend`
- **Image**: multi-stage build (Node 22 for the build, `nginx:alpine` for runtime).
- **Exposed port**: 8080 (or 443 with a certificate).
- **Volumes**: none (stateless).
- **Responsibilities**: serving the UI, proxying `/api/*`, applying security headers.

### `backend`
- **Image**: `python:3.12-slim` + dependencies (`uv` for fast installs).
- **Internal port**: 8000 (not exposed outside the Docker network).
- **Volumes**: none in production (logs via stdout/journald).
- **Responsibilities**: REST API, auth, DB access, audit log.

### `postgres`
- **Image**: `postgres:16-alpine`.
- **Port**: 5432 (not exposed outside the Docker network).
- **Volumes**: `netforge_pgdata:/var/lib/postgresql/data`.
- **Responsibilities**: persistent storage. System of record for everything.

### `redis` (optional)
- **Image**: `redis:8-alpine`.
- **Port**: 6379 (not exposed outside the Docker network — Redis has no
  authentication by default, and the cache holds session records).
- **Volumes**: `netforge_redisdata:/data` (`appendonly yes`).
- **Responsibilities**: three caches, none of which is a system of record.
  1. **Session cache** — the `(session cookie → user)` resolution every
     authenticated request otherwise costs two SELECTs to rebuild. Short TTL
     (`CACHE_SESSION_TTL_SECONDS`, default 30s) plus explicit eviction on
     logout, because instant revocation is the reason sessions live in a table
     rather than in a JWT.
  2. **Read cache** — the expensive assembled reads (`/api/topology`,
     `/api/search`, `/api/subnets/tree`, `/api/subnets/capacity-overview`).
     Keys embed a one-query fingerprint of the inventory tables, so a write
     changes the key: a reader can never be served a pre-write payload, and
     there is no invalidation step to get wrong.
  3. **Rate-limit counters** — only when `RATE_LIMIT_STORE=redis`. Same
     fleet-wide budget as the Postgres default, via an atomic Lua
     check-and-increment instead of an UPSERT.

  Set `REDIS_URL=` (empty) and every one of those falls back to Postgres; the
  stack behaves exactly as it did before this service existed. See
  `backend/app/cache.py` for the degradation policy — a Redis outage is always
  a cache miss, never an error.

## Repository layout

```
netforge/
├── README.md
├── docker-compose.yml
├── docker-compose.dev.yml
├── .env.example
├── docs/                        # these .md files
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/versions/        # DB migrations
│   └── app/
│       ├── main.py              # FastAPI app creation
│       ├── config.py            # Pydantic settings
│       ├── db.py                # SQLAlchemy engine
│       ├── auth/                # pluggable providers (github, oidc, dev) + middleware
│       ├── middleware/          # rate limiting
│       ├── models/              # SQLAlchemy ORM
│       ├── schemas/             # Pydantic (request/response)
│       ├── routers/             # endpoints by domain
│       │   ├── health.py
│       │   ├── auth.py
│       │   ├── sites.py
│       │   ├── rooms.py
│       │   ├── vlans.py
│       │   ├── vrfs.py
│       │   ├── subnets.py
│       │   ├── ips.py
│       │   ├── devices.py
│       │   ├── switches.py
│       │   ├── ports.py
│       │   ├── cables.py
│       │   ├── links.py
│       │   ├── topology.py
│       │   ├── search.py
│       │   ├── snapshots.py
│       │   ├── imports.py
│       │   ├── exports.py
│       │   ├── webhooks.py
│       │   ├── audit.py
│       │   └── ai/              # optional, gated behind AI_PROVIDER — query,
│       │                        # insights, suggestions, drafts, csv_mapping,
│       │                        # conversations, schedules, pdf_export,
│       │                        # status, usage, integrity, streaming
│       ├── services/            # business logic (one module per router,
│       │   │                    # plus errors.py, search.py, audit.py, ...)
│       │   └── ai/              # advisor, nl_query, csv_mapping, scheduler,
│       │                        # provider adapters (anthropic/openai/gemini)
│       └── utils/                # ssrf.py (SSRF-safe outbound calls), request.py
├── frontend/
│   ├── Dockerfile
│   ├── nginx.conf
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── tailwind.config.js
│   ├── index.html
│   └── src/
│       ├── main.ts
│       ├── App.vue
│       ├── router/
│       ├── stores/              # Pinia
│       ├── api/                 # generated axios client
│       ├── views/               # pages
│       ├── components/
│       └── assets/
└── scripts/
    ├── backup.sh                # pg_dump to Veeam directory
    └── restore.sh
```

## Technical choices — rationale

### Why FastAPI
- Strict typing via Pydantic → solid API contracts.
- Auto-generated OpenAPI → a typed Vue client for free.
- Native async → good for endpoints that will do SNMP in v2.
- Gentle learning curve, very good docs.

### Why PostgreSQL over SQLite/MariaDB
- Native `INET` and `CIDR` types: uniqueness constraints on subnets, "IP contained in this subnet" queries in pure SQL.
- Exclusion constraints (`EXCLUDE USING gist`): prevents two subnets from overlapping.
- `GiST` index on `INET`: very fast lookups.
- Solid transactions and FK constraints for the audit log.

### Why Vue 3 over React
- SFC syntax (`<template>/<script>/<style>`) readable for a sysadmin who isn't a full-time frontend dev.
- More compact ecosystem (Pinia for state, official Vue Router).
- Cytoscape.js integrates as well as with React.

### Why Cytoscape.js for topology
- Built-in layout engines (dagre, breadthfirst, cose).
- **Compound nodes** — a node can name a `parent`, which is what lets sites
  and rooms render as group boxes around the switches and devices they hold.
  The hierarchy is computed in `services/topology.py` and shipped in the
  payload, so the browser never rebuilds it.
- Performance on 100+ nodes without slowing down.
- Clear events API (click, hover, drag).
- No React dependency like `react-flow`.

The canvas is pointer-driven and has no keyboard model, so it is marked
`aria-hidden`. The accessible path is the topology page's **List view**, which
renders the same nodes and edges as two real tables — the graph is a second
presentation of that data, never the only one.

## Typical flow — looking up a port

1. User types "PC-COMPTA-03" in the global search bar (`GlobalSearch.vue` component).
2. Frontend sends `GET /api/search?q=PC-COMPTA-03`.
3. Backend queries the `ip`, `port`, `switch` tables via a `UNION ALL`.
4. Frontend receives a result: `{ type: "port", switch_id: 3, port_number: 14 }`.
5. User clicks → navigation to `/switches/3?port=14`.
6. Switch page loads `GET /api/switches/3` (switch + all its ports with their IPs/MACs).
7. Auto-scroll to port 14, details shown in a side panel.

## Typical flow — entering a new IP

1. User on `/subnets/12` sees the list of IPs with their status.
2. Clicks on a free IP (e.g. `10.0.30.47`).
3. The `IpEditor.vue` modal opens, prefilled with the IP.
4. User enters the hostname, MAC, picks an existing device or creates one.
5. Submit → `POST /api/ips` with Pydantic validation.
6. Backend:
   - Checks that the IP is indeed within the subnet.
   - Checks MAC uniqueness.
   - Creates the record.
   - Inserts a row into `audit_log`.
7. Frontend invalidates the Pinia cache for the subnet → the list refreshes.
