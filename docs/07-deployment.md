# 07 — Deployment

## Target

Internal Linux server (typically a Debian 12 or Ubuntu 24.04 LTS VM on Proxmox). Network access:
- Inbound HTTPS from the LAN.
- Outbound to `login.microsoftonline.com` (OIDC auth).
- Outbound to `update.docker.io` (image pulls).

Target resources: 2 vCPU, 4 GB RAM, 20 GB disk (DB included). Largely oversized for a network of this size.

## `docker-compose.yml` (production)

```yaml
services:
  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: netforge
      POSTGRES_USER: netforge
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U netforge"]
      interval: 10s
      timeout: 5s
      retries: 5

  backend:
    build: ./backend
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql+asyncpg://netforge:${POSTGRES_PASSWORD}@postgres:5432/netforge
      # Pick one provider — `oidc` covers Entra ID / Keycloak / Authentik /
      # Google Workspace; `github` covers GitHub OAuth. Never set this to
      # `dev` in production (the factory refuses to start when SESSION_COOKIE_SECURE=true).
      AUTH_PROVIDER: oidc
      OIDC_ISSUER_URL: ${OIDC_ISSUER_URL}
      OIDC_CLIENT_ID: ${OIDC_CLIENT_ID}
      OIDC_CLIENT_SECRET: ${OIDC_CLIENT_SECRET}
      SESSION_SIGNING_KEY: ${SESSION_SIGNING_KEY}
      SESSION_COOKIE_SECURE: "true"
      PUBLIC_URL: ${PUBLIC_URL}
      BOOTSTRAP_ADMIN_EMAIL: ${BOOTSTRAP_ADMIN_EMAIL}
      # Tighter than the defaults so a runaway script can't burn through DB
      # connections. Raise if you have legitimate batch writers.
      RATE_LIMIT_WRITES_PER_WINDOW: "60"
      RATE_LIMIT_WINDOW_SECONDS: "60"
      LOG_LEVEL: info

  frontend:
    build: ./frontend
    restart: unless-stopped
    depends_on:
      - backend
    ports:
      - "443:443"
      - "80:80"
    volumes:
      - ./certs:/etc/nginx/certs:ro

volumes:
  pgdata:
```

## `.env.example`

```dotenv
# Public URL used to build the redirect URIs
PUBLIC_URL=https://netforge.example.local

# PostgreSQL
POSTGRES_PASSWORD=change-me-generate-a-32-char-random

# OIDC — example values for Entra ID; see docs/06-auth.md for other IdPs.
# Issuer URL is the base that exposes /.well-known/openid-configuration:
#   Entra:    https://login.microsoftonline.com/<tenant-id>/v2.0
#   Keycloak: https://<host>/realms/<realm>
OIDC_ISSUER_URL=https://login.microsoftonline.com/00000000-0000-0000-0000-000000000000/v2.0
OIDC_CLIENT_ID=00000000-0000-0000-0000-000000000000
OIDC_CLIENT_SECRET=change-me

# Cookie signing key (openssl rand -hex 32)
SESSION_SIGNING_KEY=change-me

# The first email that logs in is automatically promoted to admin
BOOTSTRAP_ADMIN_EMAIL=admin@example.com
```

## Nginx reverse proxy (inside the frontend container)

`frontend/nginx.conf`:

```nginx
server {
    listen 80;
    server_name netforge.example.local;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name netforge.example.local;

    ssl_certificate     /etc/nginx/certs/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Security headers — kept in sync with frontend/nginx.conf and
    # docs/11-security.md. style-src 'unsafe-inline' is Tailwind JIT;
    # rsms.me feeds the Inter webfont (drop both lines if you self-host).
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://rsms.me; img-src 'self' data:; font-src 'self' data: https://rsms.me; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'" always;

    root /usr/share/nginx/html;
    index index.html;

    # API proxy
    location /api/ {
        proxy_pass http://backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 60s;
    }

    # SPA fallback
    location / {
        try_files $uri $uri/ /index.html;
    }

    # cache for hashed assets
    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
```

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

## Logs

- Backend and Nginx write to stdout/stderr → picked up by Docker → shipped to journald or Loki.
- Rotation: `max-size: 10m`, `max-file: 5` in `daemon.json`.
- Default level `info`, switchable to `debug` via the `LOG_LEVEL` env var.

## Updates

Workflow:
1. `git pull` on the server.
2. `docker compose build backend frontend`.
3. `docker compose up -d` (recreates the modified containers).
4. `docker compose exec backend alembic upgrade head` if there is a new migration.
5. `docker compose logs -f backend` to check.

No automated CI/CD to production for v1 — conscious manual deployment (the internal network diff is critical).

## Monitoring

- HTTP healthcheck `GET /api/health` returns `{ status: "ok", db: "ok", uptime_s: N }` — to be integrated on the Zabbix side as a "Netforge" template.
- Zabbix alert if `/api/health` is down > 5 min.
- Alert if DB usage exceeds 80% of disk.

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
