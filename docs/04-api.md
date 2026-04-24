# 04 — API REST

Toutes les routes sont préfixées par `/api`. Format JSON exclusivement. Auth par cookie de session (voir [06-auth.md](06-auth.md)).

## Conventions

- **Pagination** : `?page=1&page_size=50` sur toutes les listes, réponses paginées dans `{ items, total, page, page_size }`.
- **Filtres** : query string, ex: `/api/ips?subnet_id=12&status=assigned`.
- **Tri** : `?sort=field` ou `?sort=-field` (desc).
- **Erreurs** : format standard `{ error: { code, message, details } }` avec codes HTTP cohérents.
- **Validation** : Pydantic gère la validation d'entrée, réponses 422 avec détail par champ.
- **Dates** : ISO 8601 UTC.

## Auth

| Méthode | Chemin | Description |
|---------|--------|-------------|
| GET | `/api/auth/login` | Redirige vers Entra ID (flow authorization code + PKCE) |
| GET | `/api/auth/callback` | Callback OIDC, crée/MAJ user, pose cookie de session |
| POST | `/api/auth/logout` | Détruit la session, redirige vers Entra ID logout |
| GET | `/api/auth/me` | Retourne `{ id, email, display_name, role }` de l'utilisateur courant |

## Sites & rooms

| Méthode | Chemin | Description |
|---------|--------|-------------|
| GET | `/api/sites` | Liste |
| POST | `/api/sites` | Créer (admin) |
| GET | `/api/sites/{id}` | Détail + rooms associées |
| PUT | `/api/sites/{id}` | MAJ (admin) |
| DELETE | `/api/sites/{id}` | Supprimer si pas de switches/subnets liés (admin) |
| GET | `/api/rooms` | Liste, filtrable par `site_id` |
| POST | `/api/rooms` | Créer (admin) |
| GET | `/api/rooms/{id}` | Détail |
| PUT | `/api/rooms/{id}` | MAJ (admin) |
| DELETE | `/api/rooms/{id}` | Supprimer (admin) |

## VLANs

| Méthode | Chemin | Description |
|---------|--------|-------------|
| GET | `/api/vlans` | Liste |
| POST | `/api/vlans` | Créer (admin) |
| GET | `/api/vlans/{id}` | Détail + subnets + ports utilisateurs |
| PUT | `/api/vlans/{id}` | MAJ (admin) |
| DELETE | `/api/vlans/{id}` | Supprimer si non utilisé (admin) |

## Subnets

| Méthode | Chemin | Description |
|---------|--------|-------------|
| GET | `/api/subnets` | Liste avec stats `{ total, used, free, percent_used }` |
| POST | `/api/subnets` | Créer (admin) |
| GET | `/api/subnets/{id}` | Détail |
| GET | `/api/subnets/{id}/ips` | Toutes les IPs du subnet (attribuées + libres calculées) |
| PUT | `/api/subnets/{id}` | MAJ (admin) |
| DELETE | `/api/subnets/{id}` | Supprimer en cascade des IPs (admin, confirmation front) |

Exemple réponse `/api/subnets/{id}/ips` :
```json
{
  "subnet": { "id": 12, "cidr": "10.0.30.0/24", "gateway": "10.0.30.1" },
  "ips": [
    { "address": "10.0.30.1", "status": "reserved", "hostname": "gw-vlan30" },
    { "address": "10.0.30.2", "status": "assigned", "hostname": "srv-ad-01", "mac": "aa:bb:cc:dd:ee:ff" },
    { "address": "10.0.30.3", "status": "free" },
    ...
  ]
}
```

## IPs

| Méthode | Chemin | Description |
|---------|--------|-------------|
| GET | `/api/ips` | Liste filtrable `?subnet_id=&status=&q=` |
| POST | `/api/ips` | Réserver/attribuer une IP (admin) |
| GET | `/api/ips/{id}` | Détail |
| PUT | `/api/ips/{id}` | MAJ (admin) |
| DELETE | `/api/ips/{id}` | Libérer (admin) |
| POST | `/api/subnets/{id}/next-free` | Retourne la prochaine IP libre du subnet (utilitaire) |

## Devices

| Méthode | Chemin | Description |
|---------|--------|-------------|
| GET | `/api/devices` | Liste filtrable `?type=&room_id=&q=` |
| POST | `/api/devices` | Créer (admin) |
| GET | `/api/devices/{id}` | Détail + IPs + ports connectés |
| PUT | `/api/devices/{id}` | MAJ (admin) |
| DELETE | `/api/devices/{id}` | Supprimer (admin) — dissocie IPs et ports |

## Switches

| Méthode | Chemin | Description |
|---------|--------|-------------|
| GET | `/api/switches` | Liste |
| POST | `/api/switches` | Créer + génère les N ports (admin) |
| GET | `/api/switches/{id}` | Détail avec tous les ports |
| PUT | `/api/switches/{id}` | MAJ méta (admin) |
| DELETE | `/api/switches/{id}` | Supprimer + ports + liens (admin, confirmation) |

## Ports

| Méthode | Chemin | Description |
|---------|--------|-------------|
| GET | `/api/switches/{switch_id}/ports` | Liste des ports du switch |
| GET | `/api/ports/{id}` | Détail |
| PUT | `/api/ports/{id}` | MAJ (label, VLAN, device, notes) (admin) |
| POST | `/api/ports/{id}/vlans` | Ajouter VLAN tagué à un trunk (admin) |
| DELETE | `/api/ports/{id}/vlans/{vlan_id}` | Retirer VLAN tagué (admin) |

## Links (topologie)

| Méthode | Chemin | Description |
|---------|--------|-------------|
| GET | `/api/links` | Liste |
| POST | `/api/links` | Créer un lien entre 2 ports (admin) |
| DELETE | `/api/links/{id}` | Supprimer (admin) |

## Topologie

| Méthode | Chemin | Description |
|---------|--------|-------------|
| GET | `/api/topology` | Graphe complet format Cytoscape : `{ nodes: [...], edges: [...] }` |
| GET | `/api/topology?site_id=3` | Filtré par site |

Exemple réponse :
```json
{
  "nodes": [
    { "data": { "id": "sw-1", "label": "SW-SRV-01", "type": "switch", "ports_count": 48 } },
    { "data": { "id": "sw-2", "label": "SW-ETAGE-01", "type": "switch", "ports_count": 24 } }
  ],
  "edges": [
    { "data": { "id": "l-1", "source": "sw-1", "target": "sw-2", "speed": "10G", "type": "fiber" } }
  ]
}
```

## Recherche globale

| Méthode | Chemin | Description |
|---------|--------|-------------|
| GET | `/api/search?q=...` | Recherche sur IP, hostname, MAC, switch name, port label, device name |

Réponse :
```json
{
  "results": [
    { "type": "ip", "id": 3421, "label": "10.0.30.47", "context": "srv-ad-01 (VLAN 30)" },
    { "type": "device", "id": 88, "label": "srv-ad-01", "context": "Site Siège / Salle SRV-01" },
    { "type": "port", "id": 712, "label": "SW-SRV-01 / port 14", "context": "Bureau compta 3" }
  ]
}
```

## Import / Export CSV

| Méthode | Chemin | Description |
|---------|--------|-------------|
| POST | `/api/imports/{entity}` | Multipart CSV upload. `entity` ∈ `subnets`, `vlans`, `ips`, `switches`, `ports`, `devices`, `links` |
| GET | `/api/exports/{entity}` | Stream CSV |

Voir [08-import-csv.md](08-import-csv.md) pour les formats attendus.

## Audit log

| Méthode | Chemin | Description |
|---------|--------|-------------|
| GET | `/api/audit` | Liste paginée, filtres `?entity=&entity_id=&user_id=&from=&to=` |
| GET | `/api/audit/{id}` | Détail avant/après (JSON diff) |

Seuls les `admin` peuvent consulter le log complet. Les `viewer` ne voient que leurs propres actions (aucune en pratique vu leur rôle).

## Codes d'erreur

| Code | Signification |
|------|---------------|
| `AUTH_REQUIRED` | 401 — pas de session valide |
| `FORBIDDEN` | 403 — rôle insuffisant |
| `NOT_FOUND` | 404 — entité absente |
| `VALIDATION_ERROR` | 422 — payload invalide, détails par champ |
| `CONFLICT` | 409 — ex: subnet chevauchant, MAC déjà utilisée |
| `BUSINESS_RULE` | 400 — ex: IP hors subnet, lien sur port inexistant |
| `RATE_LIMITED` | 429 — login bruteforce (rate limit sur `/auth/login`) |
| `INTERNAL_ERROR` | 500 — catch-all, logué côté serveur avec trace_id retourné au client |

## OpenAPI

FastAPI expose automatiquement `/api/docs` (Swagger) et `/api/redoc`. En prod ces routes sont protégées derrière l'auth admin ou désactivées selon la config.
