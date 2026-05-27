"""Dev-only auth provider: bypasses any IdP and signs the user in directly.

**NEVER enable this in production.** Two guards block accidental
exposure: the factory raises if `SESSION_COOKIE_SECURE=true`, and this
class refuses to start if `PUBLIC_URL` doesn't resolve to a loopback
host — those are the two strongest "is this production?" signals we
have.

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
from urllib.parse import urlparse

from fastapi import Request, Response
from fastapi.responses import RedirectResponse

from app.auth.base import AuthProvider, UserInfo

logger = logging.getLogger("netforge")

# Stable subject — pairs with provider="dev" to keep the same dev user across logins.
_DEV_SUBJECT = "local-admin"

# Hosts that are safe to bind the dev bypass on. Anything else (a public
# DNS name, a LAN IP) is rejected at provider construction because the
# dev login endpoint creates an admin session on every hit — a remote
# attacker reaching it gets admin instantly, no credentials needed.
#
# 0.0.0.0 is NOT included: it's the wildcard bind that means "every
# interface" and is the exact misconfiguration that exposes the dev
# provider to the LAN. Operators who want loopback should set
# localhost / 127.0.0.1 explicitly. (The docker-compose port mapping
# to 127.0.0.1 is the other half of this defence.)
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _public_url_is_loopback(public_url: str) -> bool:
    try:
        host = (urlparse(public_url).hostname or "").lower()
    except ValueError:
        return False
    return host in _LOOPBACK_HOSTS


class DevAuthProvider(AuthProvider):
    name = "dev"

    def __init__(
        self,
        email: str,
        display_name: str,
        public_url: str = "http://localhost",
    ) -> None:
        if not _public_url_is_loopback(public_url):
            raise RuntimeError(
                f"AUTH_PROVIDER=dev refuses to start with PUBLIC_URL={public_url!r}. "
                "The dev bypass signs anyone hitting /api/auth/login in as admin — "
                "it must only be reachable on a loopback host (localhost / 127.0.0.1). "
                "Switch to github or oidc, or set PUBLIC_URL=http://localhost:..."
            )
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
