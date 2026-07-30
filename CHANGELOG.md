# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
No git tag has been cut yet — see [docs/07-deployment.md](docs/07-deployment.md)
for how to pin a deployment in the meantime.

## [Unreleased]

### Changed
- **The topology view is rebuilt, front and back.** The graph now draws four
  node kinds instead of one: sites and rooms as compound group boxes, with
  switches and the devices plugged into them as plates inside. Cables and
  device attachments are distinct edge kinds. Selecting a node dims everything
  outside its neighbourhood, and an inspector panel shows its location,
  hardware, port utilisation and neighbour list with one click through to the
  full record. Filters (site, room, VLAN, show-devices) are server-side, so
  the payload and its counts always describe exactly what is on screen; the
  header strip surfaces isolated switches and nodes with no room assigned.
  A permanent legend replaces the on-selection-only one.
- The topology page also has a **List view** rendering the same nodes and
  edges as two real tables. That is the accessible path — the canvas is
  pointer-only and is now correctly marked `aria-hidden` rather than
  advertising itself as a static image via `role="img"` while handling taps.
- `GET /api/topology` gained `room_id`, `vlan_id` and `include_devices` query
  parameters and returns a `stats` block. Node payloads carry `kind`,
  `entity_id`, `parent`, and (for switches) `ports_used`.

### Fixed
- Rate-limit counters in `RATE_LIMIT_STORE=memory` mode now live in one
  process-global window instead of one per middleware instance, and the test
  suite resets it between tests. Previously a process that built the app more
  than once enforced the cap once per app, and three import tests failed in
  the full suite while passing alone — cumulative counters, not a bug in the
  tests under scrutiny.
- Default AI model IDs and the cost table are current: OpenAI defaults to
  `gpt-5.5` (`gpt-5.1` was retired from ChatGPT in March 2026), Anthropic to
  `claude-sonnet-5`, and pricing rows were verified against published rates
  rather than left as placeholders. The Gemini default stays `gemini-2.5-pro`
  — the newest generally-available Pro model — with a note that it shuts down
  on 2026-10-16 and Google's named replacement is still preview-only.
- `Site.rooms` no longer cascade-deletes at the ORM level: deleting a site
  that still has rooms now surfaces the DB's `ON DELETE RESTRICT` violation
  as a 409 instead of silently destroying the rooms before the DB could
  object. `Subnet.ips`, `Switch.ports` and `Port.tagged_vlans` gained
  `passive_deletes=True` so Postgres handles their cascades in one statement.
- The `ips_check_in_subnet` trigger now raises with
  `ERRCODE = 'check_violation'` (migration 0020) so a violation maps to a
  clean 409 instead of a 500.
- CSV import: a row with more columns than the header is reported as a row
  error instead of crashing the import; the apply phase now reports **all**
  failing rows in one pass (per-row SAVEPOINT retry on integrity errors)
  instead of stopping at the first; files containing U+FFFD replacement
  characters get an explicit encoding warning; imports are capped at
  `CSV_IMPORT_MAX_ROWS` (default 50000).
- Concurrent link creation on the same port is now rejected at the DB level
  (`links_validate_port_exclusivity` trigger, migration 0022) instead of
  relying on a racy pre-check.
- Topology responses are bounded (500 nodes / 2000 edges) and flag
  `truncated: true` beyond that instead of serialising unbounded inventories.
- AI: LLM snapshot context is capped per entity type (500 rows, with explicit
  truncation notes); provider clients get explicit request timeouts; provider
  rate limits (429 / Anthropic 529) map to a dedicated `AI_RATE_LIMITED` 429
  with a single app-level retry, instead of a generic 5xx; all AI routes use
  the canonical `{"error": {code, message}}` shape and never echo raw
  provider errors (streaming included); the scheduler survives per-schedule
  bookkeeping failures and takes a Postgres advisory lock so multi-replica
  deploys can't double-fire a run; conversation `updated_at` ordering and
  draft double-apply (`SELECT … FOR UPDATE`) corrected; datetime filters on
  audit/export endpoints normalised to UTC; ILIKE search input escaped;
  cables and VRFs lists paginated.
- Frontend: `nf-legend` contrast raised above WCAG AA (3.6:1 → 6.3:1);
  topology link deletion uses the app's `ConfirmDialog` instead of
  `window.confirm`; CIDR/IP form fields validate with the shared
  `parseCidr`/`isValidIpv4` helpers (and on blur) instead of a permissive
  regex; French Settings tab label shortened to "IA"; overlay/tooltip colors
  moved onto the plate design tokens; unknown backend error codes fall back
  to a translated generic message.

### Security
- Booting with a placeholder `SESSION_SIGNING_KEY` is refused for any real
  IdP (`github`/`oidc`) regardless of `SESSION_COOKIE_SECURE`; the dev
  compose placeholder key is recognised as such.
- Refuses to boot when `CORS_ORIGINS` contains `*` (the API always runs
  credentialed CORS).
- OAuth flows send PKCE (S256) on both the OIDC and GitHub providers.
- `snmp_community` is redacted from audit-log diffs and outbound webhook
  payloads.
- Prompt-injection sanitisation now covers every free-text field shipped to
  the LLM (names, vendor/model, port labels, device names), not just
  descriptions/notes.
- AI scheduler webhooks can be HMAC-signed (`AI_WEBHOOK_SIGNING_SECRET`,
  `X-Netforge-Signature`).
- Expensive export GETs (CSV/ZIP/PDF) are rate-limited in their own bucket;
  optional audit-log retention via `AUDIT_LOG_RETENTION_DAYS` (default:
  unlimited).
- Compose hardening: `no-new-privileges` on all services, prod image tag
  defaults to a pinned version instead of `latest`, backup script writes
  dumps with `umask 077`, TLS ciphers restricted to the Mozilla
  intermediate list.

### Added
- Functional CRUD tests for sites, rooms, VLANs, devices (previously only
  auth-guard smoke tests existed for these routes).
- `pytest-cov` wired into CI with a measured coverage floor (81% at the time
  the 79% gate was added); `mypy` config plus a **blocking** CI step —
  `backend/app` type-checks clean against it; `.pre-commit-config.yaml`
  (ruff check + frontend eslint/prettier).
- Vitest coverage thresholds plus new unit tests for `utils/cidr.ts` edge
  cases, the CSV-import composables, `useApiErrorMessage`, and
  `ConfirmDialog.vue`.
- Global search results for VLANs/sites/rooms deep-link with
  `?highlight=<id>` (scroll + temporary ring on the target row).
- Playwright `globalSetup` fails fast with a clear message if the dev stack
  isn't up; e2e switch seeds clean up after themselves.
- `docker-build` CI job now caches layers via GHA (own scope from `release.yml`).
- `.env.example` documents every backend setting, including
  `WEBHOOK_ALLOW_PRIVATE_TARGETS` and `TRUSTED_PROXIES`.

## [0.1.0] - 2026-07-29

Initial tracked baseline: IPAM/infra inventory (sites, rooms, racks,
switches, ports, devices, subnets, IPs, VLANs, VRFs, links, cables), CSV
import/export, audit log, webhooks, optional AI features, pluggable auth
(OIDC, GitHub, dev), and the Vue 3 SPA frontend.
