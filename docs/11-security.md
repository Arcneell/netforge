# 11 — Sécurité

Netforge contient la cartographie réseau complète de l'organisation qui le déploie — un attaquant qui y accède sait exactement où frapper. La sécurité n'est pas optionnelle.

## Modèle de menace

| Menace | Probabilité | Impact | Mitigation |
|--------|-------------|--------|-----------|
| Vol de session via XSS | Faible | Élevé | CSP stricte, cookies HttpOnly, pas d'innerHTML non-sanitizé |
| CSRF sur mutations | Faible | Moyen | SameSite=Lax + header anti-CSRF sur opérations sensibles |
| SQL injection | Très faible | Catastrophique | ORM SQLAlchemy exclusivement, aucun SQL brut formaté |
| Bruteforce login | Moyen | Faible | Auth déléguée à Entra ID (MFA) + rate limit endpoint callback |
| Exposition publique accidentelle | Moyen | Catastrophique | App accessible LAN uniquement + Entra ID bloque sans compte |
| Vol de backup DB | Faible | Catastrophique | Backups chiffrés au repos sur repo Veeam, rotation |
| Ingénierie sociale pour créer un admin | Moyen | Élevé | Promotion admin uniquement par un admin existant, audit log |
| Fuite via export CSV | Moyen | Moyen | Export loggé dans audit, téléchargement réservé aux auth |
| Dépendances compromises (supply chain) | Faible | Élevé | `pip-audit` et `npm audit` en CI, pin des versions |

## Headers HTTP (via Nginx)

Référence dans [07-deployment.md](07-deployment.md). Récap minimum :

```
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'
Permissions-Policy: geolocation=(), microphone=(), camera=()
```

**CSP** : `'unsafe-inline'` sur `style-src` reste nécessaire avec Tailwind JIT. Pas d'`'unsafe-inline'` sur `script-src`. Pas de `connect-src` vers des domaines externes (tout passe par `/api/*` proxifié).

## XSS

- Vue 3 échappe par défaut tous les `{{ }}` et `v-bind`.
- **Jamais** de `v-html` sur une donnée utilisateur. Si un cas légitime apparaît → passer par DOMPurify.
- Les labels, descriptions, notes saisies par l'admin restent textuelles.

## SQL injection

- 100% du SQL passe par SQLAlchemy ORM ou queries paramétrées.
- Jamais de `f"SELECT ... WHERE name = '{user_input}'"`.
- Les filtres dynamiques (tri, pagination) sont whitelists : on valide que `sort_by` ∈ `{id, name, created_at, ...}` avant de construire la requête.

## CSRF

- Cookies `SameSite=Lax` bloquent la majorité des cross-site POST.
- Endpoints critiques (import, delete cascade) exigent en plus un header `X-Csrf-Token` :
  - Token généré à la connexion, stocké côté serveur dans la session.
  - Renvoyé au client via `GET /api/auth/me`.
  - Le client l'ajoute en header sur les mutations.
- Préflight CORS strict : `Access-Control-Allow-Origin` = domaine exact, pas de wildcard.

## Gestion des secrets

- Tous les secrets (`ENTRA_CLIENT_SECRET`, `POSTGRES_PASSWORD`, `SESSION_SIGNING_KEY`) vivent en variables d'env, jamais dans le code.
- `.env` dans `.gitignore`. Fichier `.env.example` commité avec des placeholders.
- En prod : `.env` à `chmod 600`, propriété `root:docker`.
- Rotation annuelle du client secret Entra ID.
- Les `snmp_community` stockés (v2) sont chiffrés via `pgcrypto` AES avec une clé master lue depuis env (`SNMP_ENCRYPTION_KEY`).

## Validation des entrées

- **Tous** les payloads API validés par Pydantic avec types stricts.
- Champs IP/CIDR/MAC utilisent les validators dédiés (`ipaddress.IPv4Network`, `ipaddress.IPv4Address`, regex MAC).
- Longueur max sur tous les champs texte (éviter DoS mémoire).
- Upload CSV : taille max 10 Mo, mime-type vérifié, parsing streamé.

## Audit log

Chaque mutation écrit une ligne dans `audit_log` :
- `user_id`, `action` (create/update/delete), `entity`, `entity_id`.
- `changes` JSONB : `{ before, after }` avec les colonnes modifiées.
- `ip_address`, `user_agent` du client.
- `created_at` timestamptz.

Consultable via `/api/audit` par les admins uniquement. **Non modifiable** via l'UI (pas d'endpoint `PUT/DELETE /api/audit/{id}`). Suppression possible par maintenance DB seulement.

Rétention : garder 2 ans. Cron mensuel purge les entrées plus vieilles.

## Permissions et rôles

Rappel [06-auth.md](06-auth.md) : 2 rôles `viewer` / `admin`. Tout endpoint d'écriture exige `admin`. Règle par défaut en cas de doute : deny.

Quand un admin veut promouvoir un user, l'action est elle-même auditée (`audit_log.entity = 'user', action = 'update', changes = { role: { before: 'viewer', after: 'admin' } }`).

## Sessions

- Durée 8h, renouvellement glissant (voir [06-auth.md](06-auth.md)).
- Cookie `HttpOnly`, `Secure`, `SameSite=Lax`.
- Purge des sessions expirées via cron PostgreSQL ou tâche de fond backend.
- Forcer déconnexion : suppression manuelle dans `sessions` (disponible dans `/settings/users` pour un admin).

## Backups

- Chiffrement au repos : le repo Veeam stocke les dumps sur un volume chiffré (BitLocker ou équivalent).
- Test de restauration semestriel obligatoire.
- Ne jamais laisser traîner un dump sur une machine perso.

## Logs

- Pas de PII dans les logs applicatifs (pas d'email complet, pas de payloads).
- Niveau `info` en prod : évènements structurés (login OK, create entity, erreur avec trace_id).
- Niveau `debug` uniquement en local dev.

## Supply chain

- **Python** : `pip-audit` en CI + pre-commit. Versions pin dans `pyproject.toml`.
- **JS** : `npm audit --audit-level=high` en CI. Lockfile commité.
- **Docker** : images de base officielles uniquement (`python:3.12-slim`, `nginx:alpine`, `postgres:16-alpine`). Pas d'image random de Docker Hub. Scan `docker scout` ponctuel.

## Accès réseau

- Serveur Netforge accessible **uniquement** depuis le LAN interne.
- Pas d'exposition Internet directe.
- Si besoin d'accès distant : passer par le VPN de l'organisation, pas d'exception.
- Règles firewall :
  - Entrant : 443 depuis VLAN admin seulement, 80 redirige 443.
  - Sortant : 443 vers `login.microsoftonline.com`, 443 vers registries Docker.

## Hardening de la VM hôte

- Debian/Ubuntu à jour, `unattended-upgrades` actif.
- SSH clé uniquement, pas de mdp.
- UFW/iptables restrictif.
- `fail2ban` sur SSH.
- Monitoring Zabbix de base (CPU, RAM, disque, services Docker).

## Incident response

En cas de compromission suspectée :

1. `docker compose down` immédiatement → isole l'app.
2. Préserver l'état : `docker compose logs > /tmp/forensic-logs.txt`, `pg_dump` complet horodaté.
3. Révoquer le client secret Entra ID (régénérer).
4. Invalider toutes les sessions : `TRUNCATE sessions`.
5. Audit du `audit_log` récent pour détecter les mutations suspectes.
6. Reset des mdp admin M365 des utilisateurs concernés.
7. Post-mortem écrit, correctif, test, remise en service.

## Checklist audit annuel

- [ ] Rotation `ENTRA_CLIENT_SECRET`.
- [ ] Revue des users `admin` — désactiver les ex-collaborateurs.
- [ ] Revue de l'audit log pour anomalies.
- [ ] Test de restauration backup.
- [ ] Scan dépendances `pip-audit` + `npm audit`.
- [ ] Mise à jour images Docker base.
- [ ] Revue CSP et headers.
- [ ] Test pénétration manuel basique (OWASP top 10 rapide).
