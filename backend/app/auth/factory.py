"""Pick the right `AuthProvider` from settings."""

from __future__ import annotations

from authlib.integrations.starlette_client import OAuth

from app.auth.base import AuthProvider
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
    raise RuntimeError(
        f"Unknown AUTH_PROVIDER={settings.auth_provider!r}. Expected 'github' or 'oidc'."
    )
