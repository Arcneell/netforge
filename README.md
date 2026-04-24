<p align="center">
  <img src="assets/logo-banner.svg" alt="Netforge" width="460">
</p>

<p align="center">
  <strong>Self-hosted IPAM and network infrastructure management.</strong><br>
  Subnets · VLANs · switches · ports · graph topology.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-0891b2.svg?style=flat-square" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/python-3.12+-3776ab.svg?style=flat-square&logo=python&logoColor=white" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/PostgreSQL-16-336791.svg?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL 16">
  <img src="https://img.shields.io/badge/Vue-3-4FC08D.svg?style=flat-square&logo=vue.js&logoColor=white" alt="Vue 3">
  <img src="https://img.shields.io/badge/status-alpha-f59e0b.svg?style=flat-square" alt="Alpha">
  <a href="https://github.com/netforge/netforge/pulls"><img src="https://img.shields.io/badge/PRs-welcome-22c55e.svg?style=flat-square" alt="PRs welcome"></a>
</p>

---

## Why Netforge

In most organizations, the network layout lives in Excel files, sticky notes, and the memory of whoever set it up. When something breaks — *"the phone on desk 14 stopped working"* — someone has to dig through spreadsheets to figure out which switch, which port, which VLAN, which IP.

Netforge brings it all into one place: **a single source of truth** for your IP plan, VLANs, switches and their cabling, with an interactive topology graph and a full audit trail of every change.

## Features

- **Full IPAM** — IPv4 subnets with overlap prevention enforced at the database level via a GiST exclusion constraint, reserved / assigned / DHCP addresses, free-address calculation done entirely in SQL.
- **VLANs** — full inventory, linked to both subnets and ports.
- **Switches & ports** — one record per switch with ports auto-generated at creation time, access / trunk / hybrid modes, native VLAN plus tagged VLAN list, connected-device tracking.
- **Interactive topology** — Cytoscape.js rendering with drag, zoom, click-for-details, automatic layouts (dagre, fcose), PNG export.
- **Global search** — `⌘K`-style bar that searches across IPs, hostnames, MACs, switch names, port labels, device names.
- **CSV import / export** — bootstrap quickly from existing spreadsheets, stream back any entity as CSV.
- **SSO authentication** — OIDC with Microsoft Entra ID (Azure AD), just-in-time user provisioning, `viewer` and `admin` roles.
- **Full audit log** — every mutation tracked with actor, timestamp, before/after diff, source IP, user agent.
- **Fully self-hosted** — no external dependency beyond your identity provider. Everything runs under Docker Compose.

## Tech stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.12 · FastAPI · SQLAlchemy 2.0 async · Alembic |
| Database | PostgreSQL 16 (native `INET` / `CIDR` / `MACADDR` types, `EXCLUDE USING gist`, business-rule triggers) |
| Frontend | Vue 3 · Vite · TypeScript · Tailwind CSS · Pinia |
| Topology | Cytoscape.js (dagre, fcose layouts) |
| Auth | OIDC Authorization Code + PKCE (Microsoft Entra ID) |
| Deployment | Docker Compose (backend + nginx + PostgreSQL) |

## Status

**Alpha.** The full specification lives under `docs/` and the backend scaffold (phase 0-1 of the roadmap) is in place. The frontend, authentication and CRUD endpoints are landing phase by phase — see [docs/10-roadmap.md](docs/10-roadmap.md).

## Quick start (development)

```bash
git clone https://github.com/<your-org>/netforge.git && cd netforge
cp .env.example .env                          # adjust values if needed

# Start Postgres + backend locally with auto-reload
docker compose -f docker-compose.dev.yml up -d

# Apply migrations and seed the default site + VLANs
docker compose -f docker-compose.dev.yml exec backend alembic upgrade head

# Smoke-test the API
curl http://localhost:8000/api/health
# → {"status":"ok","db":"ok","uptime_s":12}
```

Interactive OpenAPI docs are served at `http://localhost:8000/api/docs`.

## Production deployment

See [docs/07-deployment.md](docs/07-deployment.md) for the full guide (nginx reverse proxy + TLS, Entra ID setup, versioned `pg_dump` backups, monitoring).

The short version:

```bash
cp .env.example .env                          # fill in PUBLIC_URL, ENTRA_*, POSTGRES_PASSWORD
docker compose up -d
docker compose exec backend alembic upgrade head
```

## Documentation

The complete specification lives in [`docs/`](docs/).

| # | Document | Content |
|---|----------|---------|
| 01 | [Vision](docs/01-vision.md) | Goals, audience, v1 / v2 scope, non-goals |
| 02 | [Architecture](docs/02-architecture.md) | Component diagram, data flow, stack rationale |
| 03 | [Data model](docs/03-data-model.md) | PostgreSQL schema, GiST constraints, triggers |
| 04 | [REST API](docs/04-api.md) | Endpoints, payloads, error codes |
| 05 | [Frontend](docs/05-frontend.md) | Pages, components, routing, Pinia stores |
| 06 | [Authentication](docs/06-auth.md) | OIDC Entra ID, sessions, roles, CSRF |
| 07 | [Deployment](docs/07-deployment.md) | Docker Compose, reverse proxy, TLS, backups |
| 08 | [CSV import](docs/08-import-csv.md) | Expected formats per entity |
| 09 | [Topology](docs/09-topology.md) | Graph rendering, link resolution |
| 10 | [Roadmap](docs/10-roadmap.md) | Phases, milestones, estimates |
| 11 | [Security](docs/11-security.md) | Threat model, CSP, audit, incident response |

## Repository layout

```
netforge/
├── assets/                  # logo and visual assets
├── backend/                 # FastAPI application
│   ├── app/                 # models, routers, services, auth
│   ├── alembic/             # database migrations
│   ├── tests/
│   ├── Dockerfile
│   └── pyproject.toml
├── frontend/                # Vue 3 SPA (phase 6+)
├── docs/                    # full specification
├── scripts/                 # backup / restore helpers
├── docker-compose.yml       # production (phase 11)
├── docker-compose.dev.yml   # local development
└── .env.example
```

## Contributing

Contributions are welcome. For anything non-trivial, please open an issue first so we can align on the approach.

```bash
# backend dev environment without Docker
cd backend
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest                                                 # run the test suite
ruff check . && ruff format --check .                  # lint
```

Ground rules:

1. **Small, focused PRs** — one PR, one intent.
2. **Tests** — every new business rule (GiST constraint, trigger, service) ships with a `pytest` test.
3. **Migrations** — never modify the database schema by hand. Always Alembic.
4. **Security** — the rules in [docs/11-security.md](docs/11-security.md) are non-negotiable (CSP, audit log, `SameSite`, etc.).

## License

Released under the **MIT License** — see [LICENSE](LICENSE). You are free to use, modify, deploy and distribute Netforge, including commercially, provided the copyright notice and license are preserved.

## Acknowledgements

Netforge stands on the shoulders of the [FastAPI](https://fastapi.tiangolo.com/), [SQLAlchemy](https://www.sqlalchemy.org/), [PostgreSQL](https://www.postgresql.org/), [Vue](https://vuejs.org/), [Tailwind CSS](https://tailwindcss.com/) and [Cytoscape.js](https://js.cytoscape.org/) communities.
