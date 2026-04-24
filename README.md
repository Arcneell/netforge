# Netforge

> IPAM & gestion d'infra self-hosted pour le parc Mooland — subnets, VLANs, switches, ports, topologie.

Netforge est un outil d'administration réseau interne : il centralise le plan d'adressage IP, la configuration des VLANs, l'inventaire des switches et de leurs ports, et propose une vue graphique de la topologie. L'objectif est d'avoir un seul endroit pour diagnostiquer un problème réseau ("quelle IP est sur le port 24 du switch serveur ?", "combien d'IP libres sur le VLAN 30 ?", "où est branché tel téléphone Fanvil ?").

## Stack

- **Backend** : Python 3.12 + FastAPI + SQLAlchemy + Alembic
- **Base de données** : PostgreSQL 16 (types CIDR/INET natifs, contraintes d'exclusion)
- **Frontend** : Vue 3 + Vite + TypeScript + Tailwind CSS
- **Topologie graphique** : Cytoscape.js
- **Auth** : Microsoft Entra ID (OIDC) — multi-utilisateurs
- **Déploiement** : Docker Compose (backend + frontend Nginx + PostgreSQL)

## Statut

Projet en cours de spécification. Pas encore de code. Les documents dans `docs/` décrivent l'intégralité du design avant implémentation.

## Documents

| # | Document | Contenu |
|---|----------|---------|
| 01 | [Vision](docs/01-vision.md) | Objectifs, public, scope v1/v2, hors-scope |
| 02 | [Architecture](docs/02-architecture.md) | Diagramme composants, flux, stack détaillée |
| 03 | [Modèle de données](docs/03-data-model.md) | Schéma PostgreSQL, entités, relations |
| 04 | [API REST](docs/04-api.md) | Endpoints, payloads, erreurs |
| 05 | [Frontend](docs/05-frontend.md) | Pages, composants, routing, stores |
| 06 | [Authentification](docs/06-auth.md) | OIDC Entra ID, sessions, rôles |
| 07 | [Déploiement](docs/07-deployment.md) | Docker Compose, reverse proxy, backups |
| 08 | [Import CSV](docs/08-import-csv.md) | Formats attendus par type d'entité |
| 09 | [Topologie](docs/09-topology.md) | Rendu graphique, calcul des liens |
| 10 | [Roadmap](docs/10-roadmap.md) | Phases, jalons, priorités |
| 11 | [Sécurité](docs/11-security.md) | CSRF, XSS, SQLi, secrets, audit log |

## Quick start (une fois implémenté)

```bash
git clone <repo> netforge && cd netforge
cp .env.example .env   # remplir ENTRA_TENANT_ID, CLIENT_ID, CLIENT_SECRET, POSTGRES_PASSWORD
docker compose up -d
docker compose exec backend alembic upgrade head
# Ouvrir https://netforge.mooland.local
```

## Licence

Usage interne Mooland. Pas de licence publique définie à ce stade.
