<p align="center">
  <img src="assets/logo-banner.svg" alt="NetForge" width="460">
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
</p>

---

Most network documentation lives in Excel files, sticky notes, and the memory of whoever set it up. NetForge is a single source of truth for your IP plan, VLANs, switches, cabling and topology — with full change history and an interactive graph view.

## Features

- **IPAM** — IPv4 subnets with overlap prevention enforced in the database (GiST exclusion constraint), reserved / assigned / DHCP addresses, free-IP calculation in SQL.
- **Switches, ports, VLANs** — auto-generated ports, access / trunk / hybrid modes, native + tagged VLANs, connected-device tracking.
- **Interactive topology** — Cytoscape.js graph with drag, zoom, auto-layout, PNG export.
- **Global search (Ctrl/Cmd K), CSV import / export, full audit log, OIDC SSO** (Entra ID, Keycloak, Google Workspace…) or GitHub OAuth.
- **AI (optional, off by default)** — provider-agnostic (Anthropic, OpenAI, Gemini): infra advisor with SPOF / capacity / security findings, link suggestions, multi-turn Q&A on the live inventory, deterministic integrity checks, CSV mapping assistant, scheduled runs with Slack/Mattermost webhook, NL-to-action drafts (explicit-approval workflow), AI Usage dashboard with USD cost estimate, PDF export.
- **Per-IP write rate limit, strict CSP, focus-trapped modals** — hardening up front, not as an afterthought.
- **100% self-hosted** — everything runs under Docker Compose.

## Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.12 · FastAPI · SQLAlchemy 2.0 async · Alembic |
| Database | PostgreSQL 16 (`INET` / `CIDR` / `MACADDR`, GiST exclusion, triggers) |
| Frontend | Vue 3 · Vite · TypeScript · Tailwind · Pinia |
| Topology | Cytoscape.js |
| Auth | OIDC (any IdP) or GitHub OAuth — pluggable provider |
| Deployment | Docker Compose |

## Quick start

```bash
git clone https://github.com/<your-org>/netforge.git && cd netforge
cp .env.example .env
docker compose -f docker-compose.dev.yml up -d
docker compose -f docker-compose.dev.yml exec backend alembic upgrade head
```

The stack ships three services:

| Service | URL | Notes |
|---------|-----|-------|
| SPA (Vite, HMR) | <http://localhost:5173> | the page you'll use |
| Backend (FastAPI) | <http://localhost:8000/api/docs> | OpenAPI explorer |
| Postgres | localhost:5432 | psql / dump from the host |

OAuth callback URLs registered on your IdP must point at `http://localhost:5173/api/auth/callback` (the SPA proxies the callback through to the backend).

### Run the SPA on the host instead of in Docker

If you want native filesystem speed on Windows / macOS, skip the `frontend` container and run Vite yourself:

```bash
docker compose -f docker-compose.dev.yml up -d postgres backend
cd frontend
cp .env.example .env.local
npm install
npm run gen:types
npm run dev
```

For production, see [docs/07-deployment.md](docs/07-deployment.md).

## Status

**v1 ready.** Phases 0 through 10 are merged: backend foundations, auth, CRUD, search, topology, CSV import/export, the full SPA, hardening (rate limit, a11y, CSP), and Playwright E2E coverage of the critical flows. See the [roadmap](docs/10-roadmap.md) for what remains on the deploy side (TLS, Zabbix, real CSV import).

## Documentation

The full specification lives in [`docs/`](docs/) — 12 short documents covering vision, architecture, data model, REST API, frontend, auth, deployment, CSV import, topology, roadmap, security and the [end-user guide](docs/12-user-guide.md).

## Contributing

Contributions are welcome — please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a PR.

## License

MIT — see [LICENSE](LICENSE).
