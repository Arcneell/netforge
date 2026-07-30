<p align="center">
  <img src="assets/logo-banner.svg" alt="NetForge" width="460">
</p>

<p align="center">
  <strong>Self-hosted IPAM and network infrastructure management — with an optional AI co-pilot.</strong><br>
  Subnets · VLANs · switches · ports · graph topology · advisor · ask AI · drafts.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0-0E8C84.svg?style=flat-square" alt="License: AGPL-3.0"></a>
  <a href="https://github.com/Arcneell/netforge/actions/workflows/ci.yml"><img src="https://github.com/Arcneell/netforge/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <a href="https://github.com/Arcneell/netforge/pkgs/container/netforge-backend"><img src="https://img.shields.io/badge/ghcr.io-netforge-2496ED.svg?style=flat-square&logo=docker&logoColor=white" alt="Container images on GHCR"></a>
  <img src="https://img.shields.io/badge/python-3.12+-3776ab.svg?style=flat-square&logo=python&logoColor=white" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/PostgreSQL-16-336791.svg?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL 16">
  <img src="https://img.shields.io/badge/Vue-3-4FC08D.svg?style=flat-square&logo=vue.js&logoColor=white" alt="Vue 3">
</p>

---

Most network documentation lives in Excel files, sticky notes, and the memory of
whoever set it up. NetForge is a single source of truth for your IP plan, VLANs,
switches, cabling and topology — with full change history, an interactive graph
view, and an opt-in AI layer that turns the inventory into insights.

Everything runs on your own hardware. No SaaS tier, no telemetry, no account.

## Contents

- [Features](#features)
- [AI co-pilot](#ai-co-pilot-optional-off-by-default)
- [Stack](#stack)
- [Deploy it](#deploy-it) — production, from pre-built images
- [Run it locally](#run-it-locally) — development stack
- [Configuration](#configuration)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [Security](#security)
- [License](#license)

## Features

- **IPAM** — IPv4 subnets with overlap prevention enforced *in the database* (a
  GiST exclusion constraint, not application code), reserved / assigned / DHCP
  addresses, free-IP calculation in SQL, parent/child subnet hierarchy with
  containment enforced by trigger.
- **Switches, ports, VLANs** — auto-generated ports, access / trunk / hybrid
  modes, native + tagged VLANs, connected-device tracking, cable records.
- **Interactive topology** — Cytoscape.js graph with sites and rooms as compound
  groups, switches and devices as leaves, cables and device attachments as
  distinct edge kinds. Server-side filters, PNG export, and a List view as the
  accessible equivalent.
- **Global search** (<kbd>Ctrl</kbd>/<kbd>Cmd</kbd> + <kbd>K</kbd>) across
  sites, rooms, VLANs, subnets, switches and devices.
- **CSV import / export** — bulk import with header auto-detection and a
  dry-run, per-row error report, audit-log CSV stream, whole-database ZIP export.
- **Audit log** — every mutation recorded with a before/after diff, side-by-side
  coloured view, user + IP + user-agent captured. Written in the same
  transaction as the change it describes, so it cannot drift.
- **Outbound webhooks** — entity events delivered to Slack / Mattermost / Teams,
  persisted in an outbox so a crash between commit and dispatch cannot drop one.
- **Auth** — OIDC SSO (Entra ID, Keycloak, Authentik, Google Workspace,
  GitLab, …) or GitHub OAuth, plus scoped personal access tokens for scripts.
- **Hardening up front** — per-IP write rate limiting shared across workers,
  SSRF protection on admin-supplied webhook targets, strict CSP, focus-trapped
  modals, Playwright E2E on the critical flows in CI.
- **Localisation** — UI and AI responses in English and French.

## AI co-pilot (optional, off by default)

Provider-agnostic — pick **Anthropic Claude**, **OpenAI**, or **Google Gemini**
by config. Admin-only, rate-limited per user, gated behind `AI_ENABLED=false` by
default. Sites with a stricter posture can disable individual surfaces via
`AI_DRAFTS_ENABLED` / `AI_SCHEDULER_ENABLED` without giving up the rest.

| Surface | What it does |
| --- | --- |
| **Infra advisor** | Full-snapshot review — SPOF, capacity, security, segmentation, naming and redundancy findings, each with a concrete recommendation. PDF export. |
| **Suggest links** | Proposes missing port-to-port topology links from labels / notes / VLAN profiles. Accept or reject per row. |
| **Ask AI** | Multi-turn natural-language Q&A over the live inventory, SSE-streamed and rendered as Markdown with clickable entity chips. |
| **Integrity checks** | Deterministic detectors with **no LLM call and no cost** — duplicate MACs, orphan IPs, switches without ports, VLAN/subnet drift, port label collisions, missing gateways. Available even with `AI_ENABLED=false`. |
| **CSV mapping assistant** | Paste foreign headers + sample rows → canonical column mapping with confidence scores, and it rewrites the CSV header row for a one-click import. |
| **NL-to-action drafts** | Free-text request → drafted CRUD payload. An admin reviews and explicitly applies it; never auto-applied, full rollback on partial failure. |
| **Scheduled runs** | Periodic advisor / suggest-links scan that fires a webhook on *new* findings above a chosen severity. |
| **Usage dashboard** | Per-day / per-feature / per-provider token and cost estimate from public list prices. |

> [!IMPORTANT]
> With AI enabled, the inventory snapshot (sites, rooms, switches, ports, VLANs,
> subnets, devices, links) is sent to the provider's API. Keep
> `AI_ENABLED=false` if that is not acceptable — every other feature works
> without it.

## Stack

| Layer | Technology |
| --- | --- |
| Backend | Python 3.12 · FastAPI · SQLAlchemy 2.0 async · Alembic |
| Database | PostgreSQL 16 — `INET` / `CIDR` / `MACADDR`, GiST exclusion, triggers |
| Cache | Redis 8 — **optional**; sessions, heavy reads, shared rate-limit counters |
| Frontend | Vue 3 · Vite · TypeScript · Tailwind · Pinia · vue-i18n |
| Topology | Cytoscape.js (dagre + fcose layouts) |
| Auth | OIDC (any IdP) or GitHub OAuth — pluggable · personal access tokens |
| AI | Anthropic Claude · OpenAI · Google Gemini — swappable via `AI_PROVIDER` |
| Deployment | Docker Compose |

## Deploy it

Container images are published to GitHub Container Registry on every push to
`main` and on every `v*` tag. Nothing is built on your server:

- `ghcr.io/arcneell/netforge-backend`
- `ghcr.io/arcneell/netforge-frontend`

Both carry SLSA provenance and an SBOM attestation, attached to the image.

```bash
git clone https://github.com/Arcneell/netforge.git && cd netforge

# 1. Configure. Required: POSTGRES_PASSWORD, PUBLIC_URL, SESSION_SIGNING_KEY,
#    BOOTSTRAP_ADMIN_EMAIL, and the OIDC_* (or GITHUB_*) credentials for
#    whichever AUTH_PROVIDER you pick. Compose refuses to start without them.
cp .env.example .env && $EDITOR .env

# 2. TLS material — the bundled nginx expects exactly these filenames.
mkdir -p certs
cp /path/to/fullchain.pem certs/ && cp /path/to/privkey.pem certs/

# 3. Pin a version, then pull and start. `latest` moves under you on every
#    pull; pin explicitly so a restart never silently upgrades production.
export NETFORGE_VERSION=v1.0.0
docker compose pull && docker compose up -d

# 4. Apply migrations once.
docker compose exec backend alembic upgrade head
```

> [!NOTE]
> No `v*` tag has been cut yet. Until the first release, pin the reproducible
> `main-<sha>` tag that CI publishes on every push to `main` — see the
> [packages page](https://github.com/Arcneell/netforge/pkgs/container/netforge-backend)
> for the current one. Prefer a `vX.Y.Z` tag once one exists: `main-<sha>`
> history can be pruned.

Prefer to build from source instead of pulling? Same steps, but
`docker compose up -d --build` and no `pull`. Both paths are first-class — CI
builds both images on every PR so "build from source" cannot break silently.
See [docs/07-deployment.md](docs/07-deployment.md) for backups, TLS, monitoring
and the upgrade procedure.

## Run it locally

The development stack runs Vite with HMR and the backend with `--reload`, and
signs you straight in as a local admin (`AUTH_PROVIDER=dev`, loopback-only).

```bash
git clone https://github.com/Arcneell/netforge.git && cd netforge
cp .env.example .env
docker compose -f docker-compose.dev.yml up -d
docker compose -f docker-compose.dev.yml exec backend alembic upgrade head
```

Then open **<http://localhost:5173>**.

| Service | Address | Notes |
| --- | --- | --- |
| SPA (Vite, HMR) | <http://localhost:5173> | the page you'll use |
| Backend (FastAPI) | <http://localhost:8000/api/docs> | OpenAPI explorer |
| PostgreSQL | `localhost:5432` | `psql` from the host — set `POSTGRES_HOST_PORT` if 5432 is taken |
| Redis | `localhost:6379` | cache only — `REDIS_HOST_PORT` if 6379 is taken |

Testing a real IdP instead of the dev provider? Register
`http://localhost:5173/api/auth/callback` as the callback URL — the SPA proxies
it through to the backend.

> [!TIP]
> Changing a dependency means rebuilding the container's `node_modules` or venv:
> `docker compose -f docker-compose.dev.yml restart frontend` (or `backend`).
> HMR only covers source files.

### Load demo data

`scripts/build_demo_bundle.py` generates a realistic multi-site CSV bundle — 9
sites, ~75 subnets, 145 devices, 38 switches, ~55 links — with deliberately
planted problems (SPOFs, a saturated subnet, a duplicate MAC, orphan VLANs) so
the integrity checks and advisor have something to find:

```bash
python scripts/build_demo_bundle.py     # writes demo-bundle.zip at the repo root
```

Upload it via **Import → All at once (auto)**, or `POST /api/imports/bulk`.

### Run the SPA on the host

For native filesystem speed on Windows / macOS, skip the `frontend` container:

```bash
docker compose -f docker-compose.dev.yml up -d postgres redis backend
cd frontend
cp .env.example .env.local
npm install
npm run gen:types    # regenerates src/api/schema.d.ts from the live backend
npm run dev
```

## Configuration

Every knob is an environment variable, all of them documented inline in
[`.env.example`](.env.example). The three worth knowing about up front:

**`AUTH_PROVIDER`** — `oidc`, `github`, or `dev`. The `dev` provider bypasses
OAuth entirely and signs in a fixed admin; it refuses to start when
`SESSION_COOKIE_SECURE=true`, so it cannot reach production by accident.

**`REDIS_URL`** — optional, and genuinely so. Set it and Redis caches the
per-request session lookup plus the expensive assembled reads (topology graph,
global search, subnet tree, dashboard capacity). Leave it empty and every
consumer falls back to PostgreSQL: same answers, more queries. A Redis that dies
mid-request is treated as a cache miss, never an error.

Read-cache staleness is not a concern — cache keys embed a fingerprint of the
inventory tables, so a write changes the key and no reader can be served a
pre-write payload. The session cache is the one real trade-off: it puts a short
window (`CACHE_SESSION_TTL_SECONDS`, default 30s) in front of session
revocation. Logout evicts its own entry immediately; the TTL bounds a role
edited directly in the database.

**`AI_ENABLED`** — `false` by default. To turn it on:

```env
AI_ENABLED=true
AI_PROVIDER=anthropic              # anthropic | openai | gemini
AI_ANTHROPIC_API_KEY=sk-ant-...    # or AI_OPENAI_API_KEY / AI_GEMINI_API_KEY
AI_MODEL=                          # blank = the provider's default
AI_RATE_LIMIT_CALLS=20             # per user per AI_RATE_WINDOW_SECONDS (1h)
AI_DRAFTS_ENABLED=true             # false keeps the LLM strictly read-only
AI_SCHEDULER_ENABLED=true          # false keeps manual buttons, never auto-fires
```

## Documentation

The full specification lives in [`docs/`](docs/) — twelve short documents:

| | |
| --- | --- |
| [01 — Vision](docs/01-vision.md) | [07 — Deployment](docs/07-deployment.md) |
| [02 — Architecture](docs/02-architecture.md) | [08 — CSV import](docs/08-import-csv.md) |
| [03 — Data model](docs/03-data-model.md) | [09 — Topology](docs/09-topology.md) |
| [04 — REST API](docs/04-api.md) | [10 — Roadmap](docs/10-roadmap.md) |
| [05 — Frontend](docs/05-frontend.md) | [11 — Security](docs/11-security.md) |
| [06 — Auth](docs/06-auth.md) | [12 — User guide](docs/12-user-guide.md) |

The API also documents itself at `/api/docs` (Swagger) and `/api/redoc`.

## Status

v1 is shipped: backend foundations, auth, CRUD, search, topology, CSV
import/export, the full SPA, hardening, Playwright E2E, and the AI layer.
[docs/10-roadmap.md](docs/10-roadmap.md) covers what is planned next — Aruba SNMP
polling, Zabbix sync, threshold alerts.

## Contributing

Contributions of any size are welcome — bug reports, doc fixes, tests, features.
For anything non-trivial, open an issue first so we can agree on the approach
before you spend time on a PR. [CONTRIBUTING.md](CONTRIBUTING.md) covers the dev
environment, the test commands, and what CI will check.

Every PR runs lint, type checks, unit tests with a coverage gate, integration
tests against real PostgreSQL and Redis, Playwright E2E, both production image
builds, and a dependency audit. Green means green.

## Security

Please **do not** open a public issue for a vulnerability. Report it privately
through [GitHub Security Advisories](https://github.com/Arcneell/netforge/security/advisories/new).

[docs/11-security.md](docs/11-security.md) documents the threat model and the
controls in place.

## License

Copyright © 2026 NetForge contributors.

NetForge is free software, licensed under the **GNU Affero General Public
License v3.0 or later** — see [LICENSE](LICENSE) for the full text.

The AGPL is the GPL plus one extra obligation, and it is the reason it was chosen
here: **if you run a modified version of NetForge as a network service, you must
offer its source to the users of that service.** Self-hosting it unmodified for
your own organisation triggers nothing — that is the normal case and it is
entirely free. Publishing your own patched fork as a hosted product does.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE. See the License for details.
