# 07 — Deployment

## Target

Internal Linux server (typically a Debian 12 or Ubuntu 24.04 LTS VM on Proxmox). Network access:
- Inbound HTTPS from the LAN.
- Outbound to `login.microsoftonline.com` (OIDC auth).
- Outbound to `update.docker.io` (image pulls).

Target resources: 2 vCPU, 4 GB RAM, 20 GB disk (DB included). Largely oversized for a network of this size.

## Two deploy paths

Both flow through the production stack at the repo root: `docker-compose.yml`
+ `.env.example` + `frontend/nginx.prod.conf` (already baked into the image).

### Path A — pull pre-built images from GHCR (recommended)

Use this on the production server. No source tree, no build step, no Node
or Python on the host.

```bash
# 1. Get the deploy artifacts (compose file + env template + nginx config
#    used by the image, in case you want to introspect it). A shallow clone
#    is the simplest way; you can also download just the three files.
git clone --depth 1 https://github.com/Arcneell/netforge.git /opt/netforge
cd /opt/netforge

# 2. Fill in your secrets and IdP credentials. Required vars are listed at
#    the top of .env.example — the compose file refuses to start without them.
cp .env.example .env
$EDITOR .env

# 3. Drop the TLS cert + key in ./certs/ (nginx inside the frontend image
#    expects exactly these filenames):
mkdir -p certs
cp /path/to/fullchain.pem certs/fullchain.pem
cp /path/to/privkey.pem   certs/privkey.pem
chmod 600 certs/privkey.pem

# 4. Pin a version (recommended — `latest` floats with main) and bring the
#    stack up. The pull is ~80 MB total.
#    No `vX.Y.Z` tag has been cut yet at the time of writing — until the
#    first release, pin the reproducible `main-<sha>` tag release.yml
#    publishes on every push to main (see the packages page on GHCR for the
#    current sha). Once a `vX.Y.Z` tag exists, prefer that instead — it
#    won't move under you the way `main-<sha>` history can be pruned.
echo "NETFORGE_VERSION=main-abcdef0" >> .env
docker compose pull
docker compose up -d

# 5. Apply the database migrations once.
docker compose exec backend alembic upgrade head
```

Updates after a new release tag is published:

```bash
cd /opt/netforge
git pull
$EDITOR .env                                   # bump NETFORGE_VERSION
docker compose pull
docker compose up -d
docker compose exec backend alembic upgrade head   # only if migrations changed
```

### Path B — build from source on the host

Same flow as A, but step 4 becomes `docker compose up -d --build`. Use
this if you've forked the repo, patched something locally, or want to
verify the image you're running matches the source on disk. The build
takes ~3 minutes on a small VM.

```bash
docker compose up -d --build
```

`docker compose` resolves `image:` and `build:` together — once you've
built locally, the image is tagged and subsequent `docker compose up`
calls reuse it.

## Nginx reverse proxy (baked into the frontend image)

`frontend/nginx.prod.conf` is copied into the image at build time. It
terminates TLS, redirects 80→443, sets the strict security headers
documented in [11-security.md](11-security.md), and proxies `/api/*` to
the backend container. To run behind an external reverse proxy
(Traefik / Caddy / corporate LB), override the conf with a bind mount
or use the bundled HTTP-only `nginx.conf` at
`/etc/nginx/conf.d/netforge.http.conf.disabled` inside the image.

Inspect the live config with:

```bash
docker compose exec frontend cat /etc/nginx/conf.d/netforge.conf
```

Single source of truth lives at [`frontend/nginx.prod.conf`](../frontend/nginx.prod.conf).

## TLS certificates

Option A — internal certificate (recommended): issue a certificate signed by your internal CA (for example AD CS / Active Directory Certificate Services) for the chosen FQDN. All domain-joined machines trust it automatically.

Option B — Let's Encrypt via a DNS-01 challenge if the domain is public.

The `fullchain.pem` and `privkey.pem` files are mounted read-only into the container.

## DNS

A record in the internal DNS zone:
```
netforge.example.local  A  10.0.10.42   ; IP of the Docker server
```

## Backup

### Database
`scripts/backup.sh` script run via cron:

```bash
#!/bin/bash
set -euo pipefail
BACKUP_DIR=/mnt/veeam/netforge
mkdir -p "$BACKUP_DIR"
STAMP=$(date +%Y%m%d-%H%M%S)
docker compose exec -T postgres pg_dump -U netforge -Fc netforge > "$BACKUP_DIR/netforge-$STAMP.dump"
# rotation: keep 30 days
find "$BACKUP_DIR" -name 'netforge-*.dump' -mtime +30 -delete
```

Cron: daily at 02:30.

### Restore
```bash
docker compose exec -T postgres pg_restore -U netforge -d netforge --clean --if-exists < netforge-20260501-023000.dump
```

### Redis
Not backed up, on purpose. Redis holds only caches — sessions, assembled read
payloads, rate-limit counters — every one of which the backend rebuilds from
Postgres on the next request. Losing the volume costs a few slow page loads,
nothing else.

Two consequences worth knowing:

- **Restoring Postgres does not need Redis touched.** Read-cache keys embed a
  fingerprint of the inventory tables, so a restore that changes the data
  changes the keys; nothing stale can be served. Session entries expire within
  `CACHE_SESSION_TTL_SECONDS` (default 30s). If you would rather start clean:
  `docker compose exec redis redis-cli FLUSHDB`.
- **The volume exists for the AI quota, not for the cache.** With
  `RATE_LIMIT_STORE=redis` and `AI_ENABLED=true`, the per-user LLM budget lives
  in Redis, and losing it on restart hands every user a fresh hour of spend.
  That is why the bundled service runs `appendonly yes`. Leave
  `RATE_LIMIT_STORE=database` if you would rather that counter sit in a
  database you already back up.

## Logs

- Backend and Nginx write to stdout/stderr → picked up by Docker → shipped to journald or Loki.
- Rotation: `max-size: 10m`, `max-file: 5` in `daemon.json`.
- Default level `info`, switchable to `debug` via the `LOG_LEVEL` env var.

## Updates

See the per-path commands at the top of this doc — TL;DR:

- **Image path**: bump `NETFORGE_VERSION` in `.env`, then `docker compose pull && docker compose up -d`.
- **Source path**: `git pull && docker compose up -d --build`.

Either way, run `docker compose exec backend alembic upgrade head` if
the release notes mention a migration, and `docker compose logs -f backend`
to confirm the container booted clean.

No automated CI/CD to production for v1 — the deploy is a conscious
manual step (an internal-network change is critical enough to want a
human in the loop). The `release` workflow only builds and publishes
images; it never touches your server.

## Monitoring

- HTTP healthcheck `GET /api/health` returns
  `{ status: "ok", db: "ok", cache: "ok", uptime_s: N }` — to be integrated on
  the Zabbix side as a "Netforge" template.
- Zabbix alert if `/api/health` is down > 5 min.
- Alert if DB usage exceeds 80% of disk.
- `cache` is one of `disabled` (no `REDIS_URL` — the default, not a fault),
  `ok`, or `down`. A down cache deliberately leaves `status: "ok"`: every
  consumer degrades to querying Postgres, so the app is still healthy and
  paging someone at 03:00 would be wrong. Alert on the field as a warning —
  requests get slower, and with `RATE_LIMIT_STORE=redis` the write limiter
  falls back to a per-worker window (see `backend/app/middleware/rate_limit.py`).

## Go-live checklist

### Infrastructure
- [ ] Docker server provisioned (Debian 12, 2 vCPU, 4 GB RAM, 20 GB disk)
- [ ] DNS A record created and propagated
- [ ] TLS certificate issued and mounted at `./certs/{fullchain,privkey}.pem`
- [ ] Firewall: 443 in from admin VLAN, 80→443 redirect, 443 out to the IdP

### Identity
- [ ] OIDC app registered with the IdP (Entra ID / Keycloak / …)
- [ ] Redirect URI in the IdP exactly equals `${PUBLIC_URL}/api/auth/callback`
- [ ] `.env` filled in; `SESSION_SIGNING_KEY` generated with `openssl rand -hex 32`
- [ ] `SESSION_COOKIE_SECURE=true` (refuses to start with `AUTH_PROVIDER=dev`)
- [ ] `BOOTSTRAP_ADMIN_EMAIL` set to the first human who'll log in

### Bring-up
- [ ] `docker compose up -d` returns; `docker compose ps` shows every container `healthy`
- [ ] `docker compose exec backend alembic upgrade head` — no pending migrations
- [ ] First login OK; the bootstrap email is auto-promoted to admin
- [ ] `curl -sI https://<host>/api/health` returns 200 with `db: "ok"`
- [ ] Rate limit smoke-tested (70 quick POSTs → ~60 succeed, then 429s)

### Data & ops
- [ ] Daily backup cron (`scripts/backup.sh`) wired; first dump produced
- [ ] Restore drill executed against a throwaway DB (`scripts/restore.sh`)
- [ ] Zabbix template imported; `/api/health` and disk-usage alerts active
- [ ] Initial CSV import done (sites → rooms → vlans → subnets → devices →
      switches → ips → ports → links — see [08-import-csv.md](08-import-csv.md))
- [ ] [docs/12-user-guide.md](12-user-guide.md) shared with the team
