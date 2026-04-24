<p align="center">
  <img src="assets/logo-banner.svg" alt="Netforge" width="440">
</p>

<p align="center">
  <strong>IPAM & gestion d'infrastructure réseau, self-hosted.</strong><br>
  Subnets · VLANs · switches · ports · topologie graphique.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-0891b2.svg?style=flat-square" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/python-3.12+-3776ab.svg?style=flat-square&logo=python&logoColor=white" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/PostgreSQL-16-336791.svg?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL 16">
  <img src="https://img.shields.io/badge/Vue-3-4FC08D.svg?style=flat-square&logo=vue.js&logoColor=white" alt="Vue 3">
  <img src="https://img.shields.io/badge/status-alpha-f59e0b.svg?style=flat-square" alt="Alpha">
</p>

---

## Pourquoi Netforge

Dans la plupart des organisations, l'infrastructure réseau est documentée dans des fichiers Excel, des post-it et la mémoire des admins. Quand un problème arrive — *"le téléphone du bureau compta ne répond plus"* — il faut fouiller pour retrouver sur quel switch, quel port, quel VLAN, quelle IP.

Netforge centralise tout ça : **une source unique de vérité** pour votre plan d'adressage, vos VLANs, vos switches et leur câblage, avec une vue graphique de la topologie et un historique complet des changements.

## Fonctionnalités

- **IPAM complet** — subnets IPv4 avec contrainte d'unicité (pas de chevauchement possible, garanti en base via une contrainte d'exclusion GiST), IPs réservées/attribuées/DHCP, calcul des IPs libres en SQL natif.
- **VLANs** — inventaire complet, association aux subnets et aux ports.
- **Switches & ports** — fiche par switch avec génération automatique des ports à la création, mode access/trunk/hybrid, VLAN natif + VLANs tagués, équipement connecté.
- **Topologie graphique** — rendu interactif avec Cytoscape.js (drag, zoom, clic pour détails), layouts automatiques, export PNG.
- **Recherche globale** — barre de recherche type `⌘K` qui cherche sur IP, hostname, MAC, nom de switch, label de port, nom d'équipement.
- **Import / export CSV** — amorçage rapide depuis vos fichiers existants et exports périodiques.
- **Authentification SSO** — OIDC Microsoft Entra ID (Azure AD) intégré, provisioning JIT, rôles `viewer` / `admin`.
- **Audit log complet** — chaque mutation tracée (qui, quand, diff avant/après, IP, user-agent).
- **100% self-hosted** — aucune dépendance à un service externe en dehors de votre IdP, tout tourne en Docker Compose.

## Stack technique

| Couche | Technologie |
|--------|-------------|
| Backend | Python 3.12 · FastAPI · SQLAlchemy 2.0 async · Alembic |
| Base de données | PostgreSQL 16 (types `INET`/`CIDR`/`MACADDR` natifs, contraintes `EXCLUDE USING gist`, triggers métier) |
| Frontend | Vue 3 · Vite · TypeScript · Tailwind CSS · Pinia |
| Topologie | Cytoscape.js (layouts dagre, fcose) |
| Auth | OIDC Authorization Code + PKCE (Microsoft Entra ID) |
| Déploiement | Docker Compose (backend + nginx + Postgres) |

## Statut

Projet **en alpha** — la spécification complète est livrée (voir `docs/`), le backend est scaffolé (phase 0-1 de la roadmap). Le frontend, l'authentification et les CRUD arrivent par phases. Voir [docs/10-roadmap.md](docs/10-roadmap.md).

## Quick start (développement)

```bash
git clone https://github.com/<your-org>/netforge.git && cd netforge
cp .env.example .env                          # ajuster les valeurs si besoin

# Lance Postgres + backend en local, avec reload automatique
docker compose -f docker-compose.dev.yml up -d

# Applique les migrations et seed les VLANs / site par défaut
docker compose -f docker-compose.dev.yml exec backend alembic upgrade head

# Vérifie que tout répond
curl http://localhost:8000/api/health
# → {"status":"ok","db":"ok","uptime_s":12}
```

La doc OpenAPI interactive est disponible sur `http://localhost:8000/api/docs`.

## Déploiement en production

Voir [docs/07-deployment.md](docs/07-deployment.md) pour le guide complet (reverse-proxy nginx + TLS, configuration Entra ID, backups `pg_dump` versionnés, monitoring).

En résumé :

```bash
cp .env.example .env                          # remplir PUBLIC_URL, ENTRA_*, POSTGRES_PASSWORD
docker compose up -d
docker compose exec backend alembic upgrade head
```

## Documentation

La spécification complète vit dans [`docs/`](docs/).

| # | Document | Contenu |
|---|----------|---------|
| 01 | [Vision](docs/01-vision.md) | Objectifs, public, scope v1 / v2, hors-scope |
| 02 | [Architecture](docs/02-architecture.md) | Diagramme composants, flux, stack détaillée |
| 03 | [Modèle de données](docs/03-data-model.md) | Schéma PostgreSQL, contraintes GiST, triggers |
| 04 | [API REST](docs/04-api.md) | Endpoints, payloads, codes d'erreur |
| 05 | [Frontend](docs/05-frontend.md) | Pages, composants, routing, stores Pinia |
| 06 | [Authentification](docs/06-auth.md) | OIDC Entra ID, sessions, rôles, CSRF |
| 07 | [Déploiement](docs/07-deployment.md) | Docker Compose, reverse proxy, TLS, backups |
| 08 | [Import CSV](docs/08-import-csv.md) | Formats attendus par type d'entité |
| 09 | [Topologie](docs/09-topology.md) | Rendu graphique, calcul des liens |
| 10 | [Roadmap](docs/10-roadmap.md) | Phases, jalons, estimations |
| 11 | [Sécurité](docs/11-security.md) | Modèle de menace, CSP, audit, incident response |

## Structure du repo

```
netforge/
├── assets/                  # logo, illustrations
├── backend/                 # API FastAPI
│   ├── app/                 # code applicatif (models, routers, services, auth)
│   ├── alembic/             # migrations DB
│   ├── tests/
│   ├── Dockerfile
│   └── pyproject.toml
├── frontend/                # SPA Vue 3 (phase 6+)
├── docs/                    # spécification complète
├── scripts/                 # backup / restore
├── docker-compose.yml       # prod (phase 11)
├── docker-compose.dev.yml   # dev local
└── .env.example
```

## Contribuer

Les contributions sont les bienvenues. Pour une modif non triviale, ouvrez d'abord une *issue* pour en discuter.

```bash
# environnement de dev backend sans Docker
cd backend
python -m venv .venv && source .venv/bin/activate     # Windows : .venv\Scripts\activate
pip install -e ".[dev]"
pytest                                                 # lance les tests
ruff check . && ruff format --check .                  # lint
```

Principes :

1. **Petites PRs focalisées** — une PR = un objectif.
2. **Tests** — toute nouvelle règle métier (contrainte GiST, trigger, service) s'accompagne d'un test `pytest`.
3. **Migrations** — jamais de modification directe de la DB : Alembic, toujours.
4. **Sécurité** — les règles de [docs/11-security.md](docs/11-security.md) sont non-négociables (CSP, audit log, SameSite, etc.).

## Licence

Publié sous licence **MIT** — voir [LICENSE](LICENSE). Vous êtes libres d'utiliser, modifier, déployer et distribuer Netforge, y compris en contexte commercial, tant que la mention de copyright et la licence sont conservées.

## Remerciements

Netforge s'appuie sur l'excellent travail des communautés [FastAPI](https://fastapi.tiangolo.com/), [SQLAlchemy](https://www.sqlalchemy.org/), [PostgreSQL](https://www.postgresql.org/), [Vue](https://vuejs.org/), [Tailwind CSS](https://tailwindcss.com/) et [Cytoscape.js](https://js.cytoscape.org/).
