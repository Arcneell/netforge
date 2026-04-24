# 11 — Security

Netforge contains the full network map of the organization that deploys it — an attacker who gets in knows exactly where to strike. Security is not optional.

## Threat model

| Threat | Likelihood | Impact | Mitigation |
|--------|-------------|--------|-----------|
| Session theft via XSS | Low | High | Strict CSP, HttpOnly cookies, no unsanitized innerHTML |
| CSRF on mutations | Low | Medium | SameSite=Lax + anti-CSRF header on sensitive operations |
| SQL injection | Very low | Catastrophic | SQLAlchemy ORM exclusively, no formatted raw SQL |
| Login bruteforce | Medium | Low | Auth delegated to Entra ID (MFA) + rate limit on the callback endpoint |
| Accidental public exposure | Medium | Catastrophic | App reachable on LAN only + Entra ID blocks without an account |
| DB backup theft | Low | Catastrophic | Backups encrypted at rest on the Veeam repo, with rotation |
| Social engineering to create an admin | Medium | High | Admin promotion only by an existing admin, audit log |
| Leak via CSV export | Medium | Medium | Export logged in the audit log, download requires auth |
| Compromised dependencies (supply chain) | Low | High | `pip-audit` and `npm audit` in CI, pinned versions |

## HTTP headers (via Nginx)

Reference in [07-deployment.md](07-deployment.md). Minimum recap:

```
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'
Permissions-Policy: geolocation=(), microphone=(), camera=()
```

**CSP**: `'unsafe-inline'` on `style-src` remains necessary with Tailwind JIT. No `'unsafe-inline'` on `script-src`. No `connect-src` to external domains (everything goes through the proxied `/api/*`).

## XSS

- Vue 3 escapes every `{{ }}` and `v-bind` by default.
- **Never** use `v-html` on user-controlled data. If a legitimate case comes up → use DOMPurify.
- Labels, descriptions, notes entered by the admin stay textual.

## SQL injection

- 100% of SQL goes through the SQLAlchemy ORM or parameterized queries.
- Never `f"SELECT ... WHERE name = '{user_input}'"`.
- Dynamic filters (sort, pagination) are whitelisted: we validate that `sort_by` ∈ `{id, name, created_at, ...}` before building the query.

## CSRF

- `SameSite=Lax` cookies block the bulk of cross-site POSTs.
- Critical endpoints (import, cascading delete) additionally require an `X-Csrf-Token` header:
  - Token generated at login, stored server-side in the session.
  - Returned to the client via `GET /api/auth/me`.
  - The client adds it as a header on mutations.
- Strict CORS preflight: `Access-Control-Allow-Origin` = exact domain, no wildcard.

## Secret management

- All secrets (`ENTRA_CLIENT_SECRET`, `POSTGRES_PASSWORD`, `SESSION_SIGNING_KEY`) live in environment variables, never in the code.
- `.env` is in `.gitignore`. A `.env.example` file is committed with placeholders.
- In production: `.env` set to `chmod 600`, owned by `root:docker`.
- Annual rotation of the Entra ID client secret.
- Stored `snmp_community` values (v2) are encrypted via `pgcrypto` AES with a master key read from env (`SNMP_ENCRYPTION_KEY`).

## Input validation

- **All** API payloads are validated by Pydantic with strict types.
- IP/CIDR/MAC fields use dedicated validators (`ipaddress.IPv4Network`, `ipaddress.IPv4Address`, MAC regex).
- Max length on every text field (to avoid memory DoS).
- CSV upload: max size 10 MB, mime-type checked, streamed parsing.

## Audit log

Every mutation writes a row in `audit_log`:
- `user_id`, `action` (create/update/delete), `entity`, `entity_id`.
- `changes` JSONB: `{ before, after }` with the modified columns.
- Client `ip_address`, `user_agent`.
- `created_at` timestamptz.

Consulted via `/api/audit` by admins only. **Non-editable** via the UI (no `PUT/DELETE /api/audit/{id}` endpoint). Deletion is only possible through DB maintenance.

Retention: keep 2 years. A monthly cron purges older entries.

## Permissions and roles

Recall [06-auth.md](06-auth.md): 2 roles `viewer` / `admin`. Every write endpoint requires `admin`. Default rule when in doubt: deny.

When an admin promotes a user, the action itself is audited (`audit_log.entity = 'user', action = 'update', changes = { role: { before: 'viewer', after: 'admin' } }`).

## Sessions

- Duration 8h, sliding renewal (see [06-auth.md](06-auth.md)).
- Cookie `HttpOnly`, `Secure`, `SameSite=Lax`.
- Expired sessions purged via a PostgreSQL cron or a backend background task.
- Force logout: manual deletion from `sessions` (available in `/settings/users` for an admin).

## Backups

- Encryption at rest: the Veeam repo stores the dumps on an encrypted volume (BitLocker or equivalent).
- Mandatory semi-annual restore test.
- Never leave a dump lying around on a personal machine.

## Logs

- No PII in application logs (no full email, no payloads).
- Level `info` in production: structured events (login OK, entity creation, error with `trace_id`).
- Level `debug` only in local dev.

## Supply chain

- **Python**: `pip-audit` in CI + pre-commit. Versions pinned in `pyproject.toml`.
- **JS**: `npm audit --audit-level=high` in CI. Lockfile committed.
- **Docker**: only official base images (`python:3.12-slim`, `nginx:alpine`, `postgres:16-alpine`). No random images from Docker Hub. Occasional `docker scout` scans.

## Network access

- The Netforge server is reachable **only** from the internal LAN.
- No direct Internet exposure.
- If remote access is needed: go through the organization's VPN, no exceptions.
- Firewall rules:
  - Inbound: 443 from the admin VLAN only, 80 redirects to 443.
  - Outbound: 443 to `login.microsoftonline.com`, 443 to Docker registries.

## Host VM hardening

- Debian/Ubuntu up-to-date, `unattended-upgrades` enabled.
- SSH key-only, no passwords.
- Restrictive UFW/iptables.
- `fail2ban` on SSH.
- Basic Zabbix monitoring (CPU, RAM, disk, Docker services).

## Incident response

In case of suspected compromise:

1. `docker compose down` immediately → isolates the app.
2. Preserve state: `docker compose logs > /tmp/forensic-logs.txt`, full timestamped `pg_dump`.
3. Revoke the Entra ID client secret (regenerate).
4. Invalidate all sessions: `TRUNCATE sessions`.
5. Audit the recent `audit_log` for suspicious mutations.
6. Reset the M365 admin passwords of the affected users.
7. Written post-mortem, fix, test, bring back online.

## Annual audit checklist

- [ ] Rotate `ENTRA_CLIENT_SECRET`.
- [ ] Review `admin` users — deactivate former staff.
- [ ] Review the audit log for anomalies.
- [ ] Backup restore test.
- [ ] Dependency scan (`pip-audit` + `npm audit`).
- [ ] Update base Docker images.
- [ ] Review CSP and headers.
- [ ] Basic manual penetration test (quick OWASP top 10).
