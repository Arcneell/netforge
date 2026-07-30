<p align="center">
  <img src="assets/logo-banner.svg" alt="NetForge" width="460">
</p>

<p align="center">
  <strong>Self-hosted IPAM and network infrastructure management — with an optional AI co-pilot.</strong><br>
  Subnets · VLANs · switches · ports · graph topology · audit trail.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0-0E8C84.svg?style=flat-square" alt="License: AGPL-3.0"></a>
  <a href="https://github.com/Arcneell/netforge/actions/workflows/ci.yml"><img src="https://github.com/Arcneell/netforge/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <a href="https://github.com/Arcneell/netforge/pkgs/container/netforge-backend"><img src="https://img.shields.io/badge/ghcr.io-netforge-2496ED.svg?style=flat-square&logo=docker&logoColor=white" alt="Container images on GHCR"></a>
  <img src="https://img.shields.io/badge/python-3.12+-3776ab.svg?style=flat-square&logo=python&logoColor=white" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/Vue-3-4FC08D.svg?style=flat-square&logo=vue.js&logoColor=white" alt="Vue 3">
</p>

---

Most network documentation lives in Excel files, sticky notes, and the memory of
whoever set it up. NetForge is a single source of truth for your IP plan, VLANs,
switches, cabling and topology — with full change history and an interactive graph
view. Runs on your own hardware. No SaaS tier, no telemetry, no account.

## Features

- **IPAM** — IPv4 subnets with overlap prevention enforced *in the database* (a
  GiST exclusion constraint, not application code), parent/child hierarchy with
  containment enforced by trigger, free-IP calculation in SQL.
- **Switches, ports, VLANs** — auto-generated ports, access / trunk / hybrid,
  native + tagged VLANs, connected devices, cable records.
- **Topology** — Cytoscape.js graph, sites and rooms as compound groups,
  server-side filters, PNG export, plus a List view as the accessible equivalent.
- **Audit trail** — every mutation with a before/after diff, written in the same
  transaction as the change it describes so it cannot drift. Outbound webhooks
  (Slack / Mattermost / Teams) delivered via an outbox that survives a crash.
- **Auth** — OIDC SSO (Entra ID, Keycloak, Authentik, Google Workspace, GitLab, …)
  or GitHub OAuth, plus scoped personal access tokens.
- **CSV import / export**, global search (<kbd>Ctrl</kbd>/<kbd>Cmd</kbd> +
  <kbd>K</kbd>), and an English / French UI.

**AI co-pilot** — off by default (`AI_ENABLED=false`), admin-only, and
provider-agnostic across Anthropic Claude, OpenAI and Google Gemini. Infra
advisor, natural-language Q&A over the live inventory, link suggestions,
NL-to-action drafts, and zero-LLM integrity checks that work even with AI
disabled. Enabling it sends the inventory snapshot to your chosen provider —
[docs/12-user-guide.md](docs/12-user-guide.md) walks through each surface.

## Stack

Python 3.12 · FastAPI · SQLAlchemy 2.0 async · PostgreSQL 16 (`INET`/`CIDR`,
GiST exclusion, triggers) · Vue 3 · Vite · TypeScript · Tailwind ·
Cytoscape.js · Docker Compose. Redis is optional — it caches sessions and the
expensive reads; without it everything falls back to PostgreSQL.

## Deploy

Images are published to GHCR on every push to `main` and every `v*` tag, with
SLSA provenance and an SBOM attached. Nothing is built on your server.

```bash
git clone https://github.com/Arcneell/netforge.git && cd netforge
cp .env.example .env && $EDITOR .env    # every knob is documented inline
mkdir -p certs && cp /path/to/{fullchain,privkey}.pem certs/

export NETFORGE_VERSION=v1.0.0         # pin it; `latest` moves under you
docker compose pull && docker compose up -d
docker compose exec backend alembic upgrade head
```

Required in `.env`: `POSTGRES_PASSWORD`, `PUBLIC_URL`, `SESSION_SIGNING_KEY`,
`BOOTSTRAP_ADMIN_EMAIL`, and the `OIDC_*` (or `GITHUB_*`) credentials for your
`AUTH_PROVIDER`. Compose refuses to start without them.

> [!NOTE]
> No `v*` tag is cut yet. Until then pin the reproducible `main-<sha>` tag CI
> publishes — see [packages](https://github.com/Arcneell/netforge/pkgs/container/netforge-backend).

Prefer building from source? Same steps with `up -d --build` and no `pull`. Both
paths are first-class; CI builds both images on every PR. Backups, TLS and
upgrades: [docs/07-deployment.md](docs/07-deployment.md).

## Develop

Vite with HMR, backend with `--reload`, and a passwordless local admin
(`AUTH_PROVIDER=dev`, loopback-only):

```bash
cp .env.example .env
docker compose -f docker-compose.dev.yml up -d
docker compose -f docker-compose.dev.yml exec backend alembic upgrade head
```

Then <http://localhost:5173>. The API explores itself at
<http://localhost:8000/api/docs>.

`python scripts/build_demo_bundle.py` writes a `demo-bundle.zip` with 9 sites,
~75 subnets and some deliberately planted problems — upload it via
**Import → All at once** to have something to look at.

[CONTRIBUTING.md](CONTRIBUTING.md) covers running the backend outside Docker, the
test commands, and what CI checks.

## Documentation

[`docs/`](docs/) holds twelve short documents — [vision](docs/01-vision.md),
[architecture](docs/02-architecture.md), [data model](docs/03-data-model.md),
[API](docs/04-api.md), [frontend](docs/05-frontend.md), [auth](docs/06-auth.md),
[deployment](docs/07-deployment.md), [CSV import](docs/08-import-csv.md),
[topology](docs/09-topology.md), [roadmap](docs/10-roadmap.md),
[security](docs/11-security.md), [user guide](docs/12-user-guide.md).

## Contributing & security

Contributions welcome — open an issue first for anything non-trivial. Every PR
runs lint, type checks, unit tests with a coverage gate, integration tests
against real PostgreSQL and Redis, Playwright E2E, both image builds, and a
dependency audit.

Found a vulnerability? Please don't open a public issue — report it through
[Security Advisories](https://github.com/Arcneell/netforge/security/advisories/new).

## License

Copyright © 2026 NetForge contributors. Free software under the
**GNU AGPL v3.0 or later** ([LICENSE](LICENSE)).

The AGPL adds one obligation to the GPL, and it is why it was chosen: if you run
a *modified* NetForge as a network service, you must offer its source to that
service's users. Self-hosting it unmodified for your own organisation triggers
nothing.
