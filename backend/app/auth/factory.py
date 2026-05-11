"""Pick the right `AuthProvider` from settings."""

from __future__ import annotations

from authlib.integrations.starlette_client import OAuth

from app.auth.base import AuthProvider
from app.auth.dev import DevAuthProvider
from app.auth.github import GitHubProvider
from app.auth.oidc import OIDCProvider
from app.config import Settings


def make_provider(settings: Settings, oauth: OAuth) -> AuthProvider:
    """Build the configured auth provider.

    Extending: add a new branch and a new module under `app/auth/`.
    """
    name = (settings.auth_provider or "").strip().lower()
    if name == "github":
        return GitHubProvider(
            oauth,
            settings.github_client_id,
            settings.github_client_secret,
        )
    if name == "oidc":
        return OIDCProvider(
            oauth,
            settings.oidc_issuer_url,
            settings.oidc_client_id,
            settings.oidc_client_secret,
            settings.oidc_scope,
        )
    if name == "dev":
        # Strongest "is this production?" signal we have. If it's set we refuse to
        # boot rather than risk shipping a passwordless admin endpoint to the open web.
        if settings.session_cookie_secure:
            raise RuntimeError(
                "AUTH_PROVIDER=dev is forbidden when SESSION_COOKIE_SECURE=true. "
                "The dev provider has no IdP and signs anyone in as admin — it must "
                "never be used over HTTPS / in production."
            )
        return DevAuthProvider(settings.dev_admin_email, settings.dev_admin_name)
    raise RuntimeError(
        f"Unknown AUTH_PROVIDER={settings.auth_provider!r}. "
        "Expected 'github', 'oidc', or 'dev'."
    )
