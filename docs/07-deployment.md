# 07 — Déploiement

## Cible

Serveur Linux interne (probablement une VM Debian 12 ou Ubuntu 24.04 LTS sur Proxmox). Accès réseau :
- Entrant HTTPS depuis le LAN.
- Sortant vers `login.microsoftonline.com` (auth OIDC).
- Sortant vers `update.docker.io` (pulls d'images).

Ressources cibles : 2 vCPU, 4 Go RAM, 20 Go disque (DB incluse). Largement dimensionné pour un parc de cette taille.

## `docker-compose.yml` (prod)

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
      ENTRA_TENANT_ID: ${ENTRA_TENANT_ID}
      ENTRA_CLIENT_ID: ${ENTRA_CLIENT_ID}
      ENTRA_CLIENT_SECRET: ${ENTRA_CLIENT_SECRET}
      SESSION_SIGNING_KEY: ${SESSION_SIGNING_KEY}
      PUBLIC_URL: ${PUBLIC_URL}
      BOOTSTRAP_ADMIN_EMAIL: ${BOOTSTRAP_ADMIN_EMAIL}
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
# URL publique utilisée pour construire les redirect URIs
PUBLIC_URL=https://netforge.mooland.local

# PostgreSQL
POSTGRES_PASSWORD=change-me-generate-a-32-char-random

# Entra ID (cf docs/06-auth.md)
ENTRA_TENANT_ID=00000000-0000-0000-0000-000000000000
ENTRA_CLIENT_ID=00000000-0000-0000-0000-000000000000
ENTRA_CLIENT_SECRET=change-me

# Clé de signature cookies (openssl rand -hex 32)
SESSION_SIGNING_KEY=change-me

# Premier email qui se connecte devient admin automatiquement
BOOTSTRAP_ADMIN_EMAIL=informatique@mooland.fr
```

## Nginx reverse proxy (dans le container frontend)

`frontend/nginx.conf` :

```nginx
server {
    listen 80;
    server_name netforge.mooland.local;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name netforge.mooland.local;

    ssl_certificate     /etc/nginx/certs/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'" always;

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

    # cache des assets hashés
    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
```

## Certificats TLS

Option A — certif interne (recommandé) : générer un certificat signé par l'AD CS Mooland (rôle Active Directory Certificate Services) pour `netforge.mooland.local`. Tous les postes du domaine font confiance automatiquement.

Option B — Let's Encrypt via DNS-01 challenge si le domaine est public.

Les fichiers `fullchain.pem` et `privkey.pem` sont montés read-only dans le container.

## DNS

Entrée A dans la zone AD DNS Mooland :
```
netforge.mooland.local  A  10.0.10.42   ; IP du serveur Docker
```

## Backup

### Base de données
Script `scripts/backup.sh` lancé par cron :

```bash
#!/bin/bash
set -euo pipefail
BACKUP_DIR=/mnt/veeam/netforge
mkdir -p "$BACKUP_DIR"
STAMP=$(date +%Y%m%d-%H%M%S)
docker compose exec -T postgres pg_dump -U netforge -Fc netforge > "$BACKUP_DIR/netforge-$STAMP.dump"
# rotation : garder 30 jours
find "$BACKUP_DIR" -name 'netforge-*.dump' -mtime +30 -delete
```

Cron : quotidien à 02h30.

### Restauration
```bash
docker compose exec -T postgres pg_restore -U netforge -d netforge --clean --if-exists < netforge-20260501-023000.dump
```

## Logs

- Backend et Nginx écrivent sur stdout/stderr → captés par Docker → expédiés à journald ou Loki.
- Rotation : `max-size: 10m`, `max-file: 5` dans `daemon.json`.
- Niveau par défaut `info`, passable à `debug` via env `LOG_LEVEL`.

## Mise à jour

Workflow :
1. `git pull` sur le serveur.
2. `docker compose build backend frontend`.
3. `docker compose up -d` (recréé les containers modifiés).
4. `docker compose exec backend alembic upgrade head` si nouvelle migration.
5. `docker compose logs -f backend` pour vérifier.

Pas de CI/CD auto en prod pour v1 — déploiement manuel conscient (diff du parc interne critique).

## Monitoring

- Healthcheck HTTP `GET /api/health` retourne `{ status: "ok", db: "ok", uptime_s: N }` — à intégrer côté Zabbix comme template "Netforge".
- Alerte Zabbix si `/api/health` down > 5 min.
- Alerte si utilisation DB > 80% du disque.

## Checklist go-live

- [ ] Serveur Docker provisionné (Debian 12, 2 vCPU, 4 Go RAM, 20 Go disque)
- [ ] DNS A record créé et propagé
- [ ] Certif TLS émis et monté
- [ ] App Entra ID créée, secrets générés, `.env` rempli
- [ ] `docker compose up -d` OK, tous les containers `healthy`
- [ ] Migration initiale appliquée
- [ ] Premier login OK, user promu admin
- [ ] Backup quotidien testé (restauration en dev)
- [ ] Template Zabbix importé
- [ ] Import CSV initial effectué (subnets + VLANs + switches existants)
- [ ] Doc utilisateur courte envoyée à l'équipe
