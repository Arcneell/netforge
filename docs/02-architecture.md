# 02 — Architecture

## Overview

Netforge follows a classic 3-tier architecture, containerized as 3 Docker services orchestrated by `docker compose`.

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
│  - Auth middleware (OIDC Entra ID, session cookies)          │
│  - Business logic (services/)                                │
│  - SQLAlchemy 2.0 async ORM                                  │
│  - Alembic migrations                                        │
└───────────────────────────────┬─────────────────────────────┘
                                │ TCP 5432 (docker network)
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                    postgres:16 container                     │
│  - Persistent volume /var/lib/postgresql/data                │
│  - Daily backup (external cron) to Veeam repo                │
└─────────────────────────────────────────────────────────────┘
```

## Services

### `frontend`
- **Image**: multi-stage build (Node 20 for the build, `nginx:alpine` for runtime).
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
- **Responsibilities**: persistent storage.

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
│       ├── auth/                # OIDC + middleware
│       ├── models/              # SQLAlchemy ORM
│       ├── schemas/             # Pydantic (request/response)
│       ├── routers/             # endpoints by domain
│       │   ├── subnets.py
│       │   ├── vlans.py
│       │   ├── ips.py
│       │   ├── switches.py
│       │   ├── ports.py
│       │   ├── links.py
│       │   ├── topology.py
│       │   ├── imports.py
│       │   └── audit.py
│       ├── services/            # business logic
│       └── utils/
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
- Performance on 100+ nodes without slowing down.
- Clear events API (click, hover, drag).
- No React dependency like `react-flow`.

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
