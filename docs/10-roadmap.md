# 10 — Roadmap

Projet en apprentissage (alternance), donc rythme raisonnable. Estimations en demi-journées (DJ). À ajuster selon la disponibilité réelle.

## Phase 0 — Préparation (1-2 DJ)

- [ ] Créer le repo Git (GitHub ou Gitea interne selon préférence).
- [ ] Initialiser la structure de dossiers (`backend/`, `frontend/`, `docs/`).
- [ ] Créer l'app Entra ID, noter les secrets dans un gestionnaire de mdp.
- [ ] Provisionner la VM Linux Docker (Debian 12, 2 vCPU, 4 Go RAM).
- [ ] Installer Docker + Docker Compose sur la VM.
- [ ] Créer l'entrée DNS interne `netforge.mooland.local`.

## Phase 1 — Backend socle (4-6 DJ)

- [ ] `backend/pyproject.toml` avec dépendances : fastapi, uvicorn, sqlalchemy, asyncpg, alembic, pydantic, authlib, httpx, python-multipart.
- [ ] `app/main.py` : création FastAPI, CORS, middleware logging.
- [ ] `app/config.py` : settings Pydantic chargés depuis env.
- [ ] `app/db.py` : engine async SQLAlchemy.
- [ ] Alembic initialisé, migration `0001_initial` avec toutes les tables de [03-data-model.md](03-data-model.md).
- [ ] Migration `0002_seed` avec données de base (VLANs standards, site par défaut).
- [ ] Healthcheck `/api/health`.
- [ ] Dockerfile backend + `docker-compose.dev.yml` minimal (backend + postgres).
- [ ] Smoke test : `curl /api/health` OK depuis la VM.

## Phase 2 — Authentification (3-4 DJ)

- [ ] Implémenter le flow OIDC Entra ID (`app/auth/oidc.py`).
- [ ] Endpoints `/api/auth/login`, `/callback`, `/logout`, `/me`.
- [ ] Table `sessions`, création / validation / renouvellement glissant.
- [ ] Middleware `auth_middleware`.
- [ ] Dépendance `require_role`.
- [ ] JIT user provisioning + bootstrap admin par email.
- [ ] Rate limiting `slowapi` sur `/auth/*`.
- [ ] Tests manuels complets : login OK, cookie posé, /me renvoie bon user, logout vide session.

## Phase 3 — CRUD ressources core (5-7 DJ)

Ordre recommandé (chaque item = schéma Pydantic + router + service + tests pytest basiques) :

- [ ] Sites + rooms.
- [ ] VLANs.
- [ ] Subnets (avec contrainte GiST testée).
- [ ] IPs (avec trigger d'inclusion testé).
- [ ] Devices.
- [ ] Switches (avec auto-génération des ports à la création).
- [ ] Ports.
- [ ] Links.
- [ ] Audit log : trigger ou middleware SQLAlchemy `after_flush` qui enregistre les mutations.

## Phase 4 — Endpoints utilitaires (2-3 DJ)

- [ ] `/api/search` : recherche globale.
- [ ] `/api/subnets/{id}/next-free`.
- [ ] `/api/topology` : calcul du graphe.
- [ ] `/api/subnets/{id}/ips` avec calcul des IPs libres côté SQL (`generate_series` + anti-join).

## Phase 5 — Import / Export CSV (3-4 DJ)

- [ ] Parser CSV (lib `python-csv` stdlib suffit).
- [ ] Validation par entité avec Pydantic models dédiés.
- [ ] Mode dry-run.
- [ ] Rapports d'erreur ligne par ligne.
- [ ] Endpoints `/api/imports/{entity}`, `/api/exports/{entity}`.
- [ ] Tests sur fichiers CSV réalistes (prendre les Excel existants, les convertir CSV, tester).

## Phase 6 — Frontend socle (4-5 DJ)

- [ ] Init projet Vite + Vue 3 + TS + Tailwind + Pinia + Vue Router.
- [ ] Configurer `openapi-typescript` pour générer les types depuis `/api/openapi.json`.
- [ ] `AppShell.vue` avec sidebar + top bar.
- [ ] Composables `useApi`, `useAuth`.
- [ ] Router avec guard auth.
- [ ] `LoginView` (bouton "Se connecter avec Microsoft").
- [ ] Toast system + `ConfirmDialog`.
- [ ] Composants UI primitifs (Button, Input, Modal, Select).
- [ ] Dark mode switch.
- [ ] Dockerfile frontend (multi-stage build + Nginx).

## Phase 7 — Pages CRUD (6-8 DJ)

Par page : vue liste + vue détail + modales d'édition.

- [ ] Dashboard (stats agrégées).
- [ ] Subnets (liste, détail avec `IpGrid`, modale IP).
- [ ] VLANs.
- [ ] Switches (liste, détail avec `PortTable` + rack view, modale port).
- [ ] Devices.
- [ ] Sites & rooms (dans `/settings` admin).
- [ ] Audit log view.

## Phase 8 — Topologie (3-4 DJ)

- [ ] `TopologyCanvas.vue` (Cytoscape + dagre + fcose).
- [ ] `TopologyView.vue` avec panel latéral.
- [ ] Filtre par site.
- [ ] Export PNG.

## Phase 9 — Import UI (2 DJ)

- [ ] `ImportView.vue` avec dropzone, preview, rapport post-import.
- [ ] Intégration endpoints backend.

## Phase 10 — Polish & hardening (3-5 DJ)

- [ ] Loader global, états vides, error boundaries.
- [ ] Recherche globale `GlobalSearch` (cmd+k).
- [ ] Raccourcis clavier (`g s`, `g t`, ...).
- [ ] Accessibilité (focus, ARIA, contraste).
- [ ] CSP stricte vérifiée.
- [ ] Tests E2E Playwright sur les 3 parcours critiques (ajouter IP, créer switch + ports, voir topologie).
- [ ] Rate limiting complet sur les endpoints d'écriture.

## Phase 11 — Go-live v1 (2 DJ)

- [ ] Check-list de [07-deployment.md](07-deployment.md) complète.
- [ ] Certificat TLS posé.
- [ ] Backup cron actif et testé.
- [ ] Template Zabbix importé.
- [ ] Premier import CSV réel des subnets + VLANs + switches Mooland.
- [ ] Doc courte (½ page) pour le tuteur et futurs users.

## Total estimé v1

**~38 à 54 demi-journées**, soit **4 à 7 semaines** à temps partiel. À ajuster selon la disponibilité réelle et les urgences quotidiennes d'admin sys.

## Phase 12+ — v2

Dans l'ordre de valeur perçue, pas de dates :

1. **SNMP polling Aruba** : cron qui lit les tables `BRIDGE-MIB`, `IF-MIB`, `LLDP-MIB` et pré-remplit `port.connected_device`, découvre les liens LLDP automatiquement. Nécessite un worker Python dédié (container supplémentaire `netforge-poller`).
2. **Sync Zabbix** : lecture API Zabbix (hosts, interfaces) → enrichissement auto des `devices`.
3. **Alertes** : subnet > 90% plein, port down, lien qui tombe → notification Telegram (réutiliser le bot des autres Workers Mooland).
4. **Inventaire étendu** : fiches équipement complètes (contrat, garantie, série, achat).
5. **API token** pour intégrations externes (scripts PowerShell, automations).

## Risques & mitigation

| Risque | Mitigation |
|--------|-----------|
| Temps alternance limité, projet traîne | Découpage en phases livrables indépendamment. Phase 1-5 déjà utile même sans frontend (curl/postman). |
| Entra ID complexe à configurer | Doc détaillée ici. En dernier recours, fallback sur auth mdp admin (comme secret-sharer) pour dev local. |
| Contraintes PostgreSQL avancées (GiST, triggers) peu familières | Migration dédiée, tests pytest sur chaque contrainte. |
| Saisie manuelle initiale lourde | L'import CSV est conçu pour minimiser ce coût. Exports Excel existants → CSV → import massif. |
| Scope creep (envie d'ajouter SNMP en v1) | Documenter proprement en v2, tenir bon. |
