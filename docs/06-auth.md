# 06 — Authentication

## Principle

Netforge authenticates against an **external identity provider** (IdP). The FastAPI backend manages the session via a signed HTTP-only cookie (no JWT exposed to the client). The provider is **pluggable** — pick one in `AUTH_PROVIDER` and Netforge will route the login flow accordingly.

Supported out of the box:

| Provider | Protocol | `AUTH_PROVIDER` | When to pick it |
|----------|----------|-----------------|-----------------|
| GitHub | OAuth 2.0 | `github` | Open-source / developer audience, quickest setup |
| Generic OIDC | OpenID Connect | `oidc` | Microsoft Entra ID, Keycloak, Authentik, Auth0, Okta, Google Workspace, GitLab, Zitadel — anything that exposes `.well-known/openid-configuration` |

Motivations:

- **No password management** — credentials live at the IdP, not in Netforge.
- **MFA inherited** from the IdP policy.
- **Centralized offboarding** — disabling the upstream account cuts Netforge access immediately.
- **JIT provisioning** — users do not have to be pre-created in Netforge.

## Provider configuration

### GitHub

1. https://github.com/settings/developers → **OAuth Apps** → **New OAuth App**.
2. Homepage URL: `<PUBLIC_URL>` (e.g. `https://netforge.example.local`).
3. Authorization callback URL: `<PUBLIC_URL>/api/auth/callback`.
4. Once created, generate a **Client secret**.
5. Set in `.env`:
   ```
   AUTH_PROVIDER=github
   GITHUB_CLIENT_ID=...
   GITHUB_CLIENT_SECRET=...
   ```

The OAuth scopes Netforge asks for are `read:user user:email` — read-only on the user profile and primary verified email. Nothing else.

### Generic OIDC

Any IdP that publishes a `/.well-known/openid-configuration` document works. Examples:

| IdP | `OIDC_ISSUER_URL` |
|-----|-------------------|
| Microsoft Entra ID | `https://login.microsoftonline.com/<tenant-id>/v2.0` |
| Keycloak | `https://<host>/realms/<realm>` |
| Authentik | `https://<host>/application/o/<slug>/` |
| Google Workspace | `https://accounts.google.com` |
| GitLab (self-hosted or SaaS) | `https://gitlab.example.com` |

Steps:

1. Register Netforge as a confidential OAuth client at your IdP.
2. Redirect URI: `<PUBLIC_URL>/api/auth/callback`.
3. Request the scopes `openid email profile` (default — change `OIDC_SCOPE` if your IdP needs more).
4. Set in `.env`:
   ```
   AUTH_PROVIDER=oidc
   OIDC_ISSUER_URL=https://...
   OIDC_CLIENT_ID=...
   OIDC_CLIENT_SECRET=...
   OIDC_SCOPE=openid email profile
   ```

### Adding a new provider

Drop a new `AuthProvider` subclass in `app/auth/<name>.py` and add a branch in `app/auth/factory.py`. The interface is two methods: `authorize_redirect` and `authenticate`. See [`app/auth/github.py`](../backend/app/auth/github.py) as the simplest reference.

## Application flow

```
┌─────────┐    1. GET /api/auth/login    ┌─────────────┐
│         │ ───────────────────────────► │             │
│ Browser │                              │   Backend   │
│         │ ◄── 302 IdP authorize URL ── │             │
└─────────┘                              └─────────────┘
     │
     │ 2. Login (+ MFA) at the IdP
     │
     │ 3. 302 to /api/auth/callback?code=...&state=...
     ▼
┌─────────┐                              ┌─────────────┐
│         │ ─── code + state ──────────► │             │
│ Browser │                              │   Backend   │ ─ 4. Exchange code → access token
│         │ ◄── Set-Cookie session 302 ──│             │ ─ 5. Fetch user info (REST or ID token)
└─────────┘                              └─────────────┘ ─ 6. Upsert user (JIT)
                                                          7. Create session, set cookie
```

## Sessions

No JWT exposed to the client. Instead:

- The backend mints a 32-byte URL-safe random `session_id`.
- Stored in DB in `sessions(id, user_id, created_at, expires_at, ip, user_agent)`.
- Sent to the client in a `netforge_session` cookie with:
  - `HttpOnly`
  - `Secure` (when `SESSION_COOKIE_SECURE=true`)
  - `SameSite=Lax`
  - `Path=/`
  - `Max-Age=28800` (8h)
- On every authenticated request: the `get_current_user` dependency loads the session, attaches the `User` to the request.
- Sliding renewal: when less than 1h remains, `expires_at` is pushed back.

A second short-lived signed cookie (`netforge_oauth_state`) holds the OAuth `state` parameter between the authorize redirect and the callback (CSRF protection for the OAuth round-trip itself). Signed with `SESSION_SIGNING_KEY`.

Why not JWT? Because revoking a JWT requires a blocklist. With DB-backed sessions, logout / account disable = instant.

## `sessions` table

| Column | Type | Constraint |
|---------|------|-----------|
| id | varchar(64) | PK (random URL-safe token) |
| user_id | int | FK → users(id) ON DELETE CASCADE |
| created_at | timestamptz | DEFAULT now() |
| expires_at | timestamptz | NOT NULL |
| ip_address | inet | |
| user_agent | text | |

Indexes: `(user_id)`, `(expires_at)` for the purge cron.

## JIT provisioning

On the callback, the provider returns a `UserInfo(subject, email, display_name)`. The backend find-or-creates a row in `users` keyed on `(provider, subject)`.

Promotion rules on first sight:

1. If the email matches `BOOTSTRAP_ADMIN_EMAIL`, → `admin`.
2. Otherwise, if the `users` table is empty (cold start), → `admin`.
3. Otherwise, → `viewer`. An existing admin must promote them manually.

On subsequent logins, only `email` and `display_name` are refreshed (they may have changed upstream). The role is never demoted automatically.

## Roles and permissions

### `viewer`
- Read-only on every resource.
- Can use the global search, the topology, export CSV.
- **Cannot**: create, modify, delete, import, view other users' audit log.

### `admin`
- Everything a `viewer` can do + writes.
- Manages users (promote, demote, soft-delete).
- Reads the full audit log.
- Access to `/settings`.

No intermediate role in v1.

## Dependency to require a role

```python
from app.auth.dependencies import require_role
from app.models.user import UserRole

@router.post("/subnets", dependencies=[Depends(require_role(UserRole.admin))])
async def create_subnet(...): ...
```

## CSRF

Cookies with `SameSite=Lax` block most CSRF attacks on mutations. For sensitive endpoints (CSV import, cascading delete), an additional `X-Csrf-Token` header is required — emitted by `/api/auth/me` and verified server-side. (Implemented in Phase 5.)

## Logout

`POST /api/auth/logout`:
1. Deletes the session row from the DB.
2. Returns `Set-Cookie: netforge_session=; Max-Age=0`.
3. Optional (Phase 11): client-side redirect to the IdP's logout endpoint if it provides one.

## Rate limiting

Limit on `/api/auth/login` and `/api/auth/callback`: 20 req/min per IP (via `slowapi`). Protects against automated scans of the callback endpoint. (Implemented in Phase 10.)

## Secrets

- `GITHUB_CLIENT_SECRET` / `OIDC_CLIENT_SECRET`, `SESSION_SIGNING_KEY`, `POSTGRES_PASSWORD` all live in `.env` (never committed).
- In production, set via Docker environment variables.
- Rotate provider secrets annually — alert 60 days before expiry.

## Migration path between providers

Because users are keyed on `(provider, subject)`, swapping `AUTH_PROVIDER` mid-life means existing users will not be matched. Two options:

1. **Soft migration** — leave the old `provider` rows in place; users log back in via the new provider and get new rows. An admin manually merges or re-promotes them.
2. **Hard migration** — a script maps old subjects to new ones (provider-specific; e.g. GitHub `id` ↔ OIDC `sub` via email).

Plan ahead: pick the provider you intend to run with in production before onboarding users at scale.
