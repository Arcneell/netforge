<p align="center">
  <img src="assets/logo-banner.svg" alt="NetForge" width="460">
</p>

<p align="center">
  <strong>Self-hosted IPAM and network infrastructure management — with an optional AI co-pilot.</strong><br>
  Subnets · VLANs · switches · ports · graph topology · advisor · ask AI · drafts.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-0E8C84.svg?style=flat-square" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/python-3.12+-3776ab.svg?style=flat-square&logo=python&logoColor=white" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/PostgreSQL-16-336791.svg?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL 16">
  <img src="https://img.shields.io/badge/Vue-3-4FC08D.svg?style=flat-square&logo=vue.js&logoColor=white" alt="Vue 3">
  <img src="https://img.shields.io/badge/AI-Anthropic%20%C2%B7%20OpenAI%20%C2%B7%20Gemini-8b5cf6.svg?style=flat-square" alt="AI: Anthropic · OpenAI · Gemini">
  <img src="https://img.shields.io/badge/version-0.1.0-22c55e.svg?style=flat-square" alt="Version 0.1.0">
</p>

---

Most network documentation lives in Excel files, sticky notes, and the memory of whoever set it up. NetForge is a single source of truth for your IP plan, VLANs, switches, cabling and topology — with full change history, an interactive graph view, and an opt-in AI layer that turns the inventory into insights.

## Core features

- **IPAM** — IPv4 subnets with overlap prevention enforced in the database (GiST exclusion constraint), reserved / assigned / DHCP addresses, free-IP calculation in SQL.
- **Switches, ports, VLANs** — auto-generated ports, access / trunk / hybrid modes, native + tagged VLANs, connected-device tracking.
- **Interactive topology** — Cytoscape.js graph with drag, zoom, auto-layout, PNG export, manual link management.
- **Global search (Ctrl/Cmd K)** — fuzzy match across sites, rooms, vlans, subnets, switches, devices.
- **CSV import / export** — bulk import with header auto-detection + dry-run, per-row error report, audit-log CSV stream, full-DB ZIP export.
- **Audit log** — every mutation logged with before/after diff, side-by-side coloured view, user + IP + user-agent captured.
- **Auth** — OIDC SSO (Entra ID, Keycloak, Authentik, Google Workspace, GitLab, …) or GitHub OAuth, personal access tokens for scripts (Bearer auth).
- **Hardening up front** — per-IP write rate limit, strict CSP, focus-trapped modals, skeleton loaders + empty states, Playwright E2E on the critical flows (run on every PR in CI).
- **Localisation** — UI + AI responses in English and French.
- **100% self-hosted** — everything runs under Docker Compose.

## AI co-pilot (optional, off by default)

Provider-agnostic — pick **Anthropic Claude**, **OpenAI**, or **Google Gemini** by config. Admin-only, rate-limited per user, gated by `AI_ENABLED`. Privacy-sensitive sites can disable individual surfaces with `AI_DRAFTS_ENABLED` / `AI_SCHEDULER_ENABLED`.

| Surface                      | What it does                                                                                                                                                                |
| ---------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Infra advisor**            | Full-snapshot review — SPOF, capacity, security, segmentation, naming, redundancy findings, each with a concrete recommendation. PDF export.                                |
| **Suggest links**            | Scan that proposes missing port-to-port topology links from labels / notes / VLAN profiles. Accept / reject per row.                                                        |
| **Ask AI**                   | Multi-turn natural-language Q&A on the live inventory, **SSE-streamed** reply rendered as Markdown with clickable entity chips.                                             |
| **Integrity checks**         | Zero-LLM deterministic detectors (duplicate MACs, orphan IPs, switches without ports, VLAN/subnet drift, port label collisions, missing gateways) — no API call, no cost.   |
| **CSV mapping assistant**    | Paste foreign headers + sample rows → canonical NetForge column mapping with confidence scores, **auto-rewrites the CSV header row** for one-click import.                  |
| **NL-to-action drafts**      | Free-text request → drafted CRUD payload (create site / room / VLAN / subnet). Admin reviews and explicitly applies — never auto-applied, full rollback on partial failure. |
| **Scheduled runs + webhook** | Periodic advisor / suggest-links scan; fires a **Slack / Mattermost / Teams** webhook on _new_ findings above a chosen severity.                                            |
| **Usage dashboard**          | Per-day / per-feature / per-provider token + USD cost estimate from public list prices, with sparkline + breakdowns.                                                        |

Performance & safety: per-user rate limiter, prompt-injection sanitisation of free-text fields, topology snapshot cache, Anthropic prompt caching on system + large user blocks, SDK client reuse across requests.

## Stack

| Layer      | Technology                                                                   |
| ---------- | ---------------------------------------------------------------------------- |
| Backend    | Python 3.12 · FastAPI · SQLAlchemy 2.0 async · Alembic                       |
| Database   | PostgreSQL 16 (`INET` / `CIDR` / `MACADDR`, GiST exclusion, triggers)        |
| Frontend   | Vue 3 · Vite · TypeScript · Tailwind · Pinia · vue-i18n                      |
| Topology   | Cytoscape.js (dagre + fcose layouts)                                         |
| Auth       | OIDC (any IdP) or GitHub OAuth — pluggable provider · personal access tokens |
| AI         | Anthropic Claude · OpenAI · Google Gemini — swappable via `AI_PROVIDER`      |
| Deployment | Docker Compose                                                               |

## Quick start

```bash
git clone https://github.com/<your-org>/netforge.git && cd netforge
cp .env.example .env
docker compose -f docker-compose.dev.yml up -d
docker compose -f docker-compose.dev.yml exec backend alembic upgrade head
```

The stack ships three services:

| Service           | URL                              | Notes                                                                                         |
| ----------------- | -------------------------------- | --------------------------------------------------------------------------------------------- |
| SPA (Vite, HMR)   | <http://localhost:5173>          | the page you'll use                                                                           |
| Backend (FastAPI) | <http://localhost:8000/api/docs> | OpenAPI explorer                                                                              |
| Postgres          | localhost:5432                   | psql / dump from the host — set `POSTGRES_HOST_PORT` if 5432 is already taken on your machine |

OAuth callback URLs registered on your IdP must point at `http://localhost:5173/api/auth/callback` (the SPA proxies the callback through to the backend).

### Load demo data

`scripts/build_demo_bundle.py` generates a realistic multi-site CSV bundle (9 sites, ~75 subnets, 145 devices, 38 switches, ~55 links) with a handful of deliberately planted issues (SPOFs, a saturated subnet, a duplicate MAC, orphan VLANs, …) — a good way to see the integrity checks, AI advisor and bulk import in action without hand-entering data:

```bash
python scripts/build_demo_bundle.py     # writes demo-bundle.zip at the repo root
```

Upload the resulting `demo-bundle.zip` via **Import → All at once (auto)** in the UI, or `POST /api/imports/bulk`.

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

### Enable AI (optional)

Set `AI_ENABLED=true`, pick a provider and drop in its API key:

```env
AI_ENABLED=true
AI_PROVIDER=anthropic              # anthropic | openai | gemini
AI_ANTHROPIC_API_KEY=sk-ant-...    # or AI_OPENAI_API_KEY / AI_GEMINI_API_KEY
# Optional fine-tuning
AI_MODEL=                          # provider default if blank
AI_RATE_LIMIT_CALLS=20             # per user, per AI_RATE_WINDOW_SECONDS (default 1h)
AI_DRAFTS_ENABLED=true             # disable to keep the LLM strictly read-only
AI_SCHEDULER_ENABLED=true          # disable to keep manual buttons but never auto-fire
```

> **Privacy:** when AI is enabled, the inventory snapshot (sites, rooms, switches, ports, vlans, subnets, devices, links) is sent to the chosen provider's API. Keep `AI_ENABLED=false` if that's not acceptable.

For production, see [docs/07-deployment.md](docs/07-deployment.md).

## Status

**v1 shipped.** Phases 0 through 11 are merged (backend foundations, auth, CRUD, search, topology, CSV import/export, the full SPA, hardening, Playwright E2E, go-live prep), plus **Phase 12 — AI** (advisor, Ask AI with SSE streaming, suggest links, integrity, CSV mapping with auto-rename, NL-to-action drafts, scheduled runs + webhook, usage dashboard, PDF export). See the [roadmap](docs/10-roadmap.md) for what's planned in v2 (Aruba SNMP polling, Zabbix sync, threshold-based alerts).

## Documentation

The full specification lives in [`docs/`](docs/) — 12 short documents covering vision, architecture, data model, REST API, frontend, auth, deployment, CSV import, topology, roadmap, security and the [end-user guide](docs/12-user-guide.md).

## Contributing

Contributions are welcome — please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a PR.

## License

MIT — see [LICENSE](LICENSE).
