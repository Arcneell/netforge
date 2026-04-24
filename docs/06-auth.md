# 06 — Authentication

## Principle

Netforge authenticates via **Microsoft Entra ID (formerly Azure AD)** over OIDC, using the **Authorization Code + PKCE** flow. The FastAPI backend manages the session via a signed HTTP-only cookie (no JWT stored on the client side).

Motivations:
- The organization's M365 tenant is already operational → no separate password management.
- MFA inherited from the M365 policy.
- Centralized offboarding (disabling the M365 account → Netforge access cut).
- Just-in-time (JIT) automatic provisioning: a user does not need to be created manually in Netforge.

## Entra ID configuration

1. In the Entra admin portal → **App registrations** → **New registration**.
2. Name: `Netforge`.
3. Supported account types: *Accounts in this organizational directory only* (single tenant).
4. Redirect URI: `Web` → `https://netforge.example.local/api/auth/callback` (replace with your domain).
5. Once created, take note of:
   - **Application (client) ID** → `ENTRA_CLIENT_ID`
   - **Directory (tenant) ID** → `ENTRA_TENANT_ID`
6. **Certificates & secrets** → **New client secret** (expiration 24 months) → `ENTRA_CLIENT_SECRET`.
7. **API permissions** → add `openid`, `profile`, `email`, `User.Read` (Microsoft Graph, delegated). Grant admin consent.
8. **Token configuration** → add the optional `email` claim if missing from the ID token.

## Application flow

```
┌─────────┐     1. GET /api/auth/login      ┌─────────────┐
│         │ ─────────────────────────────►  │             │
│ Browser │                                 │   Backend   │
│         │ ◄─── 302 Entra authorize URL ─  │             │
└─────────┘                                 └─────────────┘
     │
     │ 2. Login + MFA on login.microsoftonline.com
     │
     │ 3. 302 to /api/auth/callback?code=...&state=...
     ▼
┌─────────┐                                 ┌─────────────┐
│         │ ───── code + state ───────────► │             │
│ Browser │                                 │   Backend   │ ─ 4. POST Entra token endpoint
│         │ ◄── Set-Cookie session + 302 ── │             │ ─ 5. Validate ID token (sig, aud, iss, exp)
└─────────┘                                 └─────────────┘ ─ 6. Upsert user (JIT)
                                                             7. Create session, set cookie
```

## Sessions

No JWT exposed to the client. Instead:

- The backend generates a `session_id` UUID v4.
- Stored in DB in `sessions(id, user_id, created_at, expires_at, ip, user_agent)`.
- Sent to the client in a `netforge_session` cookie with:
  - `HttpOnly`
  - `Secure`
  - `SameSite=Lax`
  - `Path=/`
  - `Max-Age=28800` (8h)
- On every API request: middleware reads the cookie, loads the session + user, attaches them to `request.state.user`.
- Sliding renewal: on every request, `expires_at` is pushed back if less than 1h remains.

Why not JWT? Because you cannot revoke a JWT without a blacklist. With sessions in DB, logout/deactivation = immediate removal.

## `sessions` table

| Column | Type | Constraint |
|---------|------|-----------|
| id | uuid | PK DEFAULT gen_random_uuid() |
| user_id | int | FK → users(id) ON DELETE CASCADE |
| created_at | timestamptz | DEFAULT now() |
| expires_at | timestamptz | NOT NULL |
| last_seen_at | timestamptz | DEFAULT now() |
| ip | inet | |
| user_agent | text | |

Indexes: `(user_id)`, `(expires_at)` for the purge cron.

## JIT provisioning

On the OIDC callback:

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
        role="viewer"  # default role, an admin changes it manually later
    )
    db.add(user)
else:
    user.email = email
    user.display_name = name
user.last_login_at = now()
db.commit()
```

## Roles and permissions

### `viewer`
- Read-only on every resource.
- Can use the global search, the topology, export CSV.
- **Cannot**: create, modify, delete, import, view other users' audit log.

### `admin`
- Everything a `viewer` can do + writes.
- Manages users (promote `viewer` → `admin`, demote, soft-delete).
- Reads the full audit log.
- Access to `/settings`.

No intermediate role in v1. If a "network only" or "site X only" role is needed, we'll see in v2.

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
        # sliding renewal
        await touch_session(session)
    return await call_next(request)
```

FastAPI dependency to require a role:

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

## First admin

The very first user to log in is automatically promoted to `admin` (bootstrap). Subsequent ones arrive as `viewer` and an admin must promote them manually in `/settings/users`.

Alternative: the `NETFORGE_BOOTSTRAP_ADMIN_EMAIL=admin@example.com` variable forces the admin role for that email on first login.

## CSRF

Cookies with `SameSite=Lax` block most CSRF attacks on mutations. For sensitive endpoints (CSV import, cascading delete), an extra `X-Csrf-Token` header is required — emitted by the `/api/auth/me` endpoint and verified on the backend.

## Logout

`POST /api/auth/logout`:
1. Deletes the session in DB.
2. Returns `Set-Cookie: netforge_session=; Max-Age=0`.
3. Optional: redirect to `https://login.microsoftonline.com/{tenant}/oauth2/v2.0/logout?post_logout_redirect_uri=<PUBLIC_URL>/` to also sign out from Entra.

## Rate limiting

Limit on `/api/auth/login` and `/api/auth/callback`: 20 req/min per IP (via `slowapi`). Protects against automated scans of the callback endpoint.

## Secrets

- `ENTRA_CLIENT_SECRET`, `SESSION_SIGNING_KEY`, `POSTGRES_PASSWORD` all live in `.env` (never committed).
- In production, read from Docker environment variables (Portainer / systemd env file).
- Annual `ENTRA_CLIENT_SECRET` rotation → alert 60 days before expiration via Entra.
