# 10 — Roadmap

Estimates in half-days (HD) for a part-time developer. Adjust based on actual availability.

## Phase 0 — Preparation (1-2 HD)

- [ ] Create the Git repo (GitHub or internal Gitea depending on preference).
- [ ] Initialize the folder structure (`backend/`, `frontend/`, `docs/`).
- [ ] Create the Entra ID app, store the secrets in a password manager.
- [ ] Provision the Linux Docker VM (Debian 12, 2 vCPU, 4 GB RAM).
- [ ] Install Docker + Docker Compose on the VM.
- [ ] Create the internal DNS entry (e.g. `netforge.example.local`).

## Phase 1 — Backend foundations (4-6 HD)

- [ ] `backend/pyproject.toml` with dependencies: fastapi, uvicorn, sqlalchemy, asyncpg, alembic, pydantic, authlib, httpx, python-multipart.
- [ ] `app/main.py`: FastAPI creation, CORS, logging middleware.
- [ ] `app/config.py`: Pydantic settings loaded from env.
- [ ] `app/db.py`: async SQLAlchemy engine.
- [ ] Alembic initialized, `0001_initial` migration with all tables from [03-data-model.md](03-data-model.md).
- [ ] Fresh installs start with an empty schema — populate via the bulk CSV import or CRUD UI (no seed migration).
- [ ] Healthcheck `/api/health`.
- [ ] Backend Dockerfile + minimal `docker-compose.dev.yml` (backend + postgres).
- [ ] Smoke test: `curl /api/health` OK from the VM.

## Phase 2 — Authentication (3-4 HD)

- [ ] Implement the OIDC Entra ID flow (`app/auth/oidc.py`).
- [ ] Endpoints `/api/auth/login`, `/callback`, `/logout`, `/me`.
- [ ] `sessions` table, creation / validation / sliding renewal.
- [ ] `auth_middleware` middleware.
- [ ] `require_role` dependency.
- [ ] JIT user provisioning + bootstrap admin by email.
- [ ] `slowapi` rate limiting on `/auth/*`.
- [ ] Full manual tests: login OK, cookie set, /me returns the right user, logout clears the session.

## Phase 3 — Core resource CRUD (5-7 HD)

Recommended order (each item = Pydantic schema + router + service + basic pytest tests):

- [ ] Sites + rooms.
- [ ] VLANs.
- [ ] Subnets (with the GiST constraint tested).
- [ ] IPs (with the inclusion trigger tested).
- [ ] Devices.
- [ ] Switches (with auto-generation of ports on creation).
- [ ] Ports.
- [ ] Links.
- [ ] Audit log: trigger or SQLAlchemy `after_flush` middleware that records mutations.

## Phase 4 — Utility endpoints (2-3 HD)

- [ ] `/api/search`: global search.
- [ ] `/api/subnets/{id}/next-free`.
- [ ] `/api/topology`: graph computation.
- [ ] `/api/subnets/{id}/ips` with free-IP calculation on the SQL side (`generate_series` + anti-join).

## Phase 5 — CSV import / export (3-4 HD)

- [ ] CSV parser (stdlib `python-csv` is enough).
- [ ] Per-entity validation with dedicated Pydantic models.
- [ ] Dry-run mode.
- [ ] Row-by-row error reports.
- [ ] Endpoints `/api/imports/{entity}`, `/api/exports/{entity}`.
- [ ] Tests against realistic CSV files (take the existing Excel files, convert them to CSV, test).

## Phase 6 — Frontend foundations (4-5 HD)

- [ ] Init Vite + Vue 3 + TS + Tailwind + Pinia + Vue Router project.
- [ ] Configure `openapi-typescript` to generate the types from `/api/openapi.json`.
- [ ] `AppShell.vue` with sidebar + top bar.
- [ ] Composables `useApi`, `useAuth`.
- [ ] Router with auth guard.
- [ ] `LoginView` ("Sign in with Microsoft" button).
- [ ] Toast system + `ConfirmDialog`.
- [ ] Primitive UI components (Button, Input, Modal, Select).
- [ ] Dark mode switch.
- [ ] Frontend Dockerfile (multi-stage build + Nginx).

## Phase 7 — CRUD pages (6-8 HD)

Per page: list view + detail view + edit modals.

- [ ] Dashboard (aggregated stats).
- [ ] Subnets (list, detail with `IpGrid`, IP modal).
- [ ] VLANs.
- [ ] Switches (list, detail with `PortTable` + rack view, port modal).
- [ ] Devices.
- [ ] Sites & rooms (under `/settings` admin).
- [ ] Audit log view.

## Phase 8 — Topology (3-4 HD)

- [ ] `TopologyCanvas.vue` (Cytoscape + dagre + fcose).
- [ ] `TopologyView.vue` with side panel.
- [ ] Filter by site.
- [ ] PNG export.

## Phase 9 — Import UI (2 HD)

- [ ] `ImportView.vue` with dropzone, preview, post-import report.
- [ ] Backend endpoints integration.

## Phase 10 — Polish & hardening (3-5 HD)

- [ ] Global loader, empty states, error boundaries.
- [ ] `GlobalSearch` global search (cmd+k).
- [ ] Keyboard shortcuts (`g s`, `g t`, ...).
- [ ] Accessibility (focus, ARIA, contrast).
- [ ] Strict CSP verified.
- [ ] Playwright E2E tests on the 3 critical user flows (add IP, create switch + ports, view topology).
- [ ] Full rate limiting on write endpoints.

## Phase 11 — v1 go-live (2 HD)

Code-side prep done in this repo (Phase 11 PR):
- [x] [07-deployment.md](07-deployment.md) checklist rewritten and grouped by area;
      env vars aligned with what the code actually reads.
- [x] `scripts/backup.sh` + `scripts/restore.sh` shipped and documented.
- [x] [docs/12-user-guide.md](12-user-guide.md) — half-page end-user guide.
- [x] Logo unified: site icon (`BrandMark.vue`), favicon and README banner
      now share the same hexagon + 4-node mark.

Host-side, done at install time (out of repo):
- [ ] TLS certificate issued and mounted.
- [ ] Backup cron entry installed and the first restore drill executed.
- [ ] Zabbix template imported and alerts on `/api/health`.
- [ ] First real CSV import of the existing subnets + VLANs + switches.
- [ ] [docs/12-user-guide.md](12-user-guide.md) shared with the team.

## Estimated v1 total

**~38 to 54 half-days**, i.e. **4 to 7 weeks** part-time. Adjust based on actual availability.

## Phase 12 — AI (shipped 2026-05)

A provider-agnostic AI surface — Anthropic Claude, OpenAI, Google Gemini.
All features are admin-only, rate-limited per-user, and gated by
`AI_ENABLED` (off by default for fresh installs). Privacy-sensitive
deployments can disable individual features via `AI_DRAFTS_ENABLED` and
`AI_SCHEDULER_ENABLED`.

- [x] **Suggest links** — scan that proposes missing port-to-port
      topology links from port labels / notes / VLAN profiles. Workflow:
      accept / reject each suggestion.
- [x] **Infra advisor** — full-snapshot review surfacing SPOF / capacity /
      security / segmentation / naming / redundancy / other findings,
      each with a concrete recommendation. Cached run, re-run on demand.
- [x] **Ask AI** — multi-turn natural-language Q&A on the live inventory,
      SSE-streamed reply rendered as Markdown with clickable entity chips.
- [x] **Integrity checks** — zero-LLM deterministic detectors (duplicate
      MACs, orphan IPs, switches without ports, …), shown alongside the
      advisor findings.
- [x] **CSV mapping assistant** — paste foreign headers + sample rows;
      the model proposes the canonical NetForge column mapping with
      confidence scores, and auto-rewrites the CSV header row for
      one-click import.
- [x] **Scheduled runs + webhook** — opt-in periodic advisor /
      suggest-links scan; advisor schedule can fire a Slack / Mattermost /
      Teams webhook on **new** findings above a chosen severity.
- [x] **NL-to-action drafts** — free-text request →
      LLM-drafted CRUD payload (create site / room / VLAN / subnet) that
      an admin reviews and explicitly applies. Never auto-applied.
- [x] **AI Usage dashboard** — per-day / per-feature / per-provider
      token + USD cost estimate from public list prices, with sparkline
      and breakdowns.
- [x] **PDF export** of the advisor report.
- [x] **Localisation** — AI responses + integrity check titles /
      descriptions / recommendations follow the operator's UI language
      (EN + FR shipped).
- [x] Performance & UX: per-user rate limiter, prompt-injection
      sanitisation of free-text fields, topology snapshot cache,
      Anthropic prompt caching on system + large user blocks, SDK client
      reuse across requests, axios 120s timeout on AI endpoints, full
      rollback on partial draft-apply failure.

## Phase 13+ — v2

In order of perceived value, no dates:

1. **Aruba SNMP polling**: a cron that reads `BRIDGE-MIB`, `IF-MIB`, `LLDP-MIB` tables and pre-fills `port.connected_device`, discovers LLDP links automatically. Requires a dedicated Python worker (additional `netforge-poller` container).
2. **Zabbix sync**: read the Zabbix API (hosts, interfaces) → auto-enrichment of `devices`.
3. **Alerts (non-AI)**: subnet > 90% full, port down, link dropping → configurable webhook (Slack, Telegram, Mattermost, email, etc.). The AI advisor + scheduler webhook shipped in Phase 12 covers the *insight*-driven case; this addition is for deterministic Zabbix-style thresholds.
4. **Extended inventory**: full device records (contract, warranty, serial, purchase).
5. **API token** for external integrations (PowerShell scripts, automations).

## Risks & mitigations

| Risk | Mitigation |
|--------|-----------|
| Part-time dev, project drags on | Split into phases that are independently shippable. Phases 1-5 are already useful even without a frontend (curl/postman). |
| Entra ID complex to configure | Detailed doc here. As a last resort, fall back to local admin auth for dev / evaluation. |
| Advanced PostgreSQL constraints (GiST, triggers) unfamiliar | Dedicated migration, pytest tests on every constraint. |
| Heavy initial manual data entry | CSV import is designed to minimize this cost. Existing Excel exports → CSV → bulk import. |
| Scope creep (urge to add SNMP in v1) | Document it cleanly in v2, hold the line. |
