# 06 — Authentification

## Principe

Netforge s'authentifie via **Microsoft Entra ID (ex-Azure AD)** en OIDC, flow **Authorization Code + PKCE**. Le backend FastAPI gère la session via un cookie HTTP-only signé (pas de JWT stocké côté client).

Motivations :
- Tenant M365 de l'organisation déjà opérationnel → pas de gestion de mots de passe à part.
- MFA hérité de la politique M365.
- Gestion centralisée des départs (désactivation du compte M365 → accès Netforge coupé).
- Provisioning automatique (JIT) : un utilisateur n'a pas besoin d'être créé à la main dans Netforge.

## Configuration côté Entra ID

1. Dans le portail Entra admin → **App registrations** → **New registration**.
2. Nom : `Netforge`.
3. Supported account types : *Accounts in this organizational directory only* (single tenant).
4. Redirect URI : `Web` → `https://netforge.example.local/api/auth/callback` (remplacer par votre domaine).
5. Une fois créée, noter :
   - **Application (client) ID** → `ENTRA_CLIENT_ID`
   - **Directory (tenant) ID** → `ENTRA_TENANT_ID`
6. **Certificates & secrets** → **New client secret** (expiration 24 mois) → `ENTRA_CLIENT_SECRET`.
7. **API permissions** → ajouter `openid`, `profile`, `email`, `User.Read` (Microsoft Graph, déléguées). Grant admin consent.
8. **Token configuration** → ajouter claim optionnel `email` si manquant du token ID.

## Flow applicatif

```
┌─────────┐     1. GET /api/auth/login      ┌─────────────┐
│         │ ─────────────────────────────►  │             │
│ Browser │                                 │   Backend   │
│         │ ◄─── 302 Entra authorize URL ─  │             │
└─────────┘                                 └─────────────┘
     │
     │ 2. Login + MFA sur login.microsoftonline.com
     │
     │ 3. 302 vers /api/auth/callback?code=...&state=...
     ▼
┌─────────┐                                 ┌─────────────┐
│         │ ───── code + state ───────────► │             │
│ Browser │                                 │   Backend   │ ─ 4. POST token endpoint Entra
│         │ ◄── Set-Cookie session + 302 ── │             │ ─ 5. Valide ID token (sig, aud, iss, exp)
└─────────┘                                 └─────────────┘ ─ 6. Upsert user (JIT)
                                                             7. Crée session, pose cookie
```

## Sessions

Pas de JWT exposé au client. À la place :

- Backend génère un `session_id` UUID v4.
- Stocké en DB dans `sessions(id, user_id, created_at, expires_at, ip, user_agent)`.
- Envoyé au client en cookie `netforge_session` avec :
  - `HttpOnly`
  - `Secure`
  - `SameSite=Lax`
  - `Path=/`
  - `Max-Age=28800` (8h)
- Chaque requête API : middleware lit le cookie, charge la session + user, attache à `request.state.user`.
- Renouvellement glissant : à chaque requête, `expires_at` repoussé si moins d'1h restante.

Pourquoi pas JWT ? Parce qu'on ne peut pas révoquer un JWT sans blacklist. Avec des sessions en DB, logout/désactivation = suppression immédiate.

## Table `sessions`

| Colonne | Type | Contrainte |
|---------|------|-----------|
| id | uuid | PK DEFAULT gen_random_uuid() |
| user_id | int | FK → users(id) ON DELETE CASCADE |
| created_at | timestamptz | DEFAULT now() |
| expires_at | timestamptz | NOT NULL |
| last_seen_at | timestamptz | DEFAULT now() |
| ip | inet | |
| user_agent | text | |

Index : `(user_id)`, `(expires_at)` pour le cron de purge.

## Provisioning JIT

Au callback OIDC :

```python
oid = id_token["oid"]
email = id_token["preferred_username"] or id_token["email"]
name = id_token["name"]

user = db.query(User).filter_by(entra_oid=oid).first()
if not user:
    user = User(
        entra_oid=oid,
        email=email,
        display_name=name,
        role="viewer"  # rôle par défaut, admin change manuellement ensuite
    )
    db.add(user)
else:
    user.email = email
    user.display_name = name
user.last_login_at = now()
db.commit()
```

## Rôles et permissions

### `viewer`
- Lecture seule sur toutes les ressources.
- Peut utiliser la recherche globale, la topologie, exporter CSV.
- Ne peut **pas** : créer, modifier, supprimer, importer, consulter l'audit log des autres.

### `admin`
- Tout ce que fait `viewer` + écriture.
- Gère les users (promote `viewer` → `admin`, demote, soft-delete).
- Consulte l'audit log complet.
- Accède à `/settings`.

Pas de rôle intermédiaire v1. Si besoin d'un rôle "network only" ou "site X only", on verra en v2.

## Middleware

```python
# app/auth/middleware.py
async def auth_middleware(request: Request, call_next):
    if request.url.path.startswith("/api/auth/"):
        return await call_next(request)
    if request.url.path.startswith("/api/"):
        session_id = request.cookies.get("netforge_session")
        if not session_id:
            return JSONResponse({"error": {"code": "AUTH_REQUIRED"}}, 401)
        session = await get_valid_session(session_id)
        if not session:
            return JSONResponse({"error": {"code": "AUTH_REQUIRED"}}, 401)
        request.state.user = session.user
        # renouvellement glissant
        await touch_session(session)
    return await call_next(request)
```

Dépendance FastAPI pour exiger un rôle :

```python
def require_role(*roles):
    def _dep(request: Request):
        user = request.state.user
        if user.role not in roles:
            raise HTTPException(403, {"error": {"code": "FORBIDDEN"}})
        return user
    return _dep

@router.post("/subnets", dependencies=[Depends(require_role("admin"))])
async def create_subnet(...): ...
```

## Premier admin

Le tout premier utilisateur à se connecter est automatiquement `admin` (bootstrap). Les suivants arrivent `viewer` et un admin doit les promouvoir manuellement dans `/settings/users`.

Alternative : variable `NETFORGE_BOOTSTRAP_ADMIN_EMAIL=admin@example.com` qui force le rôle admin pour cet email à la première connexion.

## CSRF

Les cookies en `SameSite=Lax` protègent contre la plupart des attaques CSRF sur mutations. Pour les endpoints sensibles (import CSV, delete en cascade), ajout d'un header `X-Csrf-Token` émis par l'endpoint `/api/auth/me` et vérifié côté backend.

## Logout

`POST /api/auth/logout` :
1. Supprime la session en DB.
2. Retourne `Set-Cookie: netforge_session=; Max-Age=0`.
3. Optionnel : redirection vers `https://login.microsoftonline.com/{tenant}/oauth2/v2.0/logout?post_logout_redirect_uri=<PUBLIC_URL>/` pour déconnecter aussi d'Entra.

## Rate limiting

Limite sur `/api/auth/login` et `/api/auth/callback` : 20 req/min par IP (via `slowapi`). Protège contre scan automatique du endpoint de callback.

## Secrets

- `ENTRA_CLIENT_SECRET`, `SESSION_SIGNING_KEY`, `POSTGRES_PASSWORD` tous dans `.env` (jamais commité).
- En prod, lecture depuis variables d'environnement Docker (Portainer / systemd env file).
- Rotation `ENTRA_CLIENT_SECRET` annuelle → alerte 60 jours avant expiration via Entra.
