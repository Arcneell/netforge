"""Dev-only auth provider: bypasses any IdP and signs the user in directly.

**NEVER enable this in production.** The factory raises if it sees
`SESSION_COOKIE_SECURE=true` together with `AUTH_PROVIDER=dev` — that
combination is the strongest signal we have that the deployment is real.

Flow:
  1. `GET /api/auth/login` → backend asks the provider for an authorize
     redirect; here we 302 straight to `/api/auth/callback`, skipping
     every external round-trip.
  2. `GET /api/auth/callback` → backend asks the provider to authenticate;
     here we return a hard-coded `UserInfo` whose `(provider, subject)`
     pair is stable, so JIT provisioning creates exactly one dev user
     and reuses it on every subsequent login.
"""

from __future__ import annotations

import logging

from fastapi import Request, Response
from fastapi.responses import RedirectResponse

from app.auth.base import AuthProvider, UserInfo

logger = logging.getLogger("netforge")

# Stable subject — pairs with provider="dev" to keep the same dev user across logins.
_DEV_SUBJECT = "local-admin"


class DevAuthProvider(AuthProvider):
    name = "dev"

    def __init__(self, email: str, display_name: str) -> None:
        self._email = email
        self._display_name = display_name
        logger.warning(
            "AUTH_PROVIDER=dev — using the dev bypass. Anyone hitting /api/auth/login "
            "is signed in as %s (admin). DO NOT use this in production.",
            email,
        )

    async def authorize_redirect(self, _request: Request, redirect_uri: str) -> Response:
        # No IdP round-trip — go straight to our own callback. The callback handler
        # will call `authenticate()` (below), upsert the user and set the session.
        return RedirectResponse(redirect_uri, status_code=302)

    async def authenticate(self, _request: Request) -> UserInfo:
        return UserInfo(
            subject=_DEV_SUBJECT,
            email=self._email,
            display_name=self._display_name,
        )
