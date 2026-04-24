# 02 — Architecture

## Vue d'ensemble

Netforge suit une architecture classique 3-tiers, conteneurisée en 3 services Docker orchestrés par `docker compose`.

```
┌─────────────────────────────────────────────────────────────┐
│                    Utilisateur (navigateur)                  │
└───────────────────────────────┬─────────────────────────────┘
                                │ HTTPS (Nginx reverse proxy)
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                  Container nginx (frontend)                  │
│  - Sert le build statique Vue 3 (dist/)                      │
│  - Proxy /api/* → backend                                    │
│  - Gère les headers CSP, HSTS, X-Frame-Options               │
└───────────────────────────────┬─────────────────────────────┘
                                │ HTTP interne (docker network)
                                ▼
┌─────────────────────────────────────────────────────────────┐
│              Container backend (FastAPI + Uvicorn)           │
│  - Routes REST /api/*                                        │
│  - Auth middleware (OIDC Entra ID, sessions cookies)         │
│  - Business logic (services/)                                │
│  - ORM SQLAlchemy 2.0 async                                  │
│  - Migrations Alembic                                        │
└───────────────────────────────┬─────────────────────────────┘
                                │ TCP 5432 (docker network)
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                    Container postgres:16                     │
│  - Volume persistant /var/lib/postgresql/data                │
│  - Backup quotidien (cron externe) vers Veeam repo           │
└─────────────────────────────────────────────────────────────┘
```

## Services

### `frontend`
- **Image** : build multi-stage (Node 20 pour le build, `nginx:alpine` pour le runtime).
- **Port exposé** : 8080 (ou 443 avec certif).
- **Volumes** : aucun (stateless).
- **Responsabilités** : servir l'UI, proxifier `/api/*`, appliquer les headers de sécurité.

### `backend`
- **Image** : `python:3.12-slim` + dépendances (`uv` pour l'install rapide).
- **Port interne** : 8000 (non exposé en dehors du network Docker).
- **Volumes** : aucun en prod (logs via stdout/journald).
- **Responsabilités** : API REST, auth, accès DB, audit log.

### `postgres`
- **Image** : `postgres:16-alpine`.
- **Port** : 5432 (non exposé hors network Docker).
- **Volumes** : `netforge_pgdata:/var/lib/postgresql/data`.
- **Responsabilités** : stockage persistant.

## Arborescence du repo

```
netforge/
├── README.md
├── docker-compose.yml
├── docker-compose.dev.yml
├── .env.example
├── docs/                        # ces fichiers .md
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/versions/        # migrations DB
│   └── app/
│       ├── main.py              # création app FastAPI
│       ├── config.py            # settings Pydantic
│       ├── db.py                # engine SQLAlchemy
│       ├── auth/                # OIDC + middleware
│       ├── models/              # SQLAlchemy ORM
│       ├── schemas/             # Pydantic (request/response)
│       ├── routers/             # endpoints par domaine
│       │   ├── subnets.py
│       │   ├── vlans.py
│       │   ├── ips.py
│       │   ├── switches.py
│       │   ├── ports.py
│       │   ├── links.py
│       │   ├── topology.py
│       │   ├── imports.py
│       │   └── audit.py
│       ├── services/            # logique métier
│       └── utils/
├── frontend/
│   ├── Dockerfile
│   ├── nginx.conf
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── tailwind.config.js
│   ├── index.html
│   └── src/
│       ├── main.ts
│       ├── App.vue
│       ├── router/
│       ├── stores/              # Pinia
│       ├── api/                 # client axios généré
│       ├── views/               # pages
│       ├── components/
│       └── assets/
└── scripts/
    ├── backup.sh                # pg_dump vers répertoire Veeam
    └── restore.sh
```

## Choix techniques — justification

### Pourquoi FastAPI
- Typage strict via Pydantic → contrats API solides.
- OpenAPI généré automatiquement → client Vue typé gratuitement.
- Async natif → bon pour les endpoints qui feront du SNMP en v2.
- Courbe d'apprentissage douce, très bonne doc.

### Pourquoi PostgreSQL et pas SQLite/MariaDB
- Types `INET` et `CIDR` natifs : contraintes d'unicité sur sous-réseaux, requêtes "IP contenue dans ce subnet" en SQL pur.
- Contraintes d'exclusion (`EXCLUDE USING gist`) : empêche deux subnets de se chevaucher.
- Index `GiST` sur `INET` : recherches très rapides.
- Transactions et contraintes FK solides pour l'audit log.

### Pourquoi Vue 3 et pas React
- Syntaxe SFC (`<template>/<script>/<style>`) lisible pour un admin sys qui n'est pas dev frontend à temps plein.
- Écosystème plus compact (Pinia pour le state, Vue Router officiel).
- Cytoscape.js s'intègre aussi bien qu'avec React.

### Pourquoi Cytoscape.js pour la topologie
- Moteur de layout intégré (dagre, breadthfirst, cose).
- Performance sur 100+ nœuds sans ramer.
- API events claire (clic, hover, drag).
- Pas de dépendance React comme `react-flow`.

## Flux type — consultation d'un port

1. User tape "PC-COMPTA-03" dans la barre de recherche globale (composant `GlobalSearch.vue`).
2. Frontend envoie `GET /api/search?q=PC-COMPTA-03`.
3. Backend interroge les tables `ip`, `port`, `switch` via un `UNION ALL`.
4. Frontend reçoit un résultat : `{ type: "port", switch_id: 3, port_number: 14 }`.
5. User clique → navigation vers `/switches/3?port=14`.
6. Page switch charge `GET /api/switches/3` (switch + tous ses ports avec leurs IPs/MACs).
7. Scroll auto sur le port 14, détails affichés dans un panel latéral.

## Flux type — saisie d'une nouvelle IP

1. User sur `/subnets/12` voit la liste des IPs avec leur état.
2. Clique sur une IP libre (ex: `10.0.30.47`).
3. Modale `IpEditor.vue` s'ouvre, pré-remplie avec l'IP.
4. User saisit hostname, MAC, choisit un équipement existant ou en crée un.
5. Submit → `POST /api/ips` avec validation Pydantic.
6. Backend :
   - Vérifie que l'IP est bien dans le subnet.
   - Vérifie l'unicité de la MAC.
   - Crée l'enregistrement.
   - Insère une ligne dans `audit_log`.
7. Frontend invalide le cache Pinia du subnet → la liste se rafraîchit.
