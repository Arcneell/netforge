"""Pick the right `AuthProvider` from settings."""

from __future__ import annotations

from authlib.integrations.starlette_client import OAuth

from app.auth.base import AuthProvider
from app.auth.dev import DevAuthProvider
from app.auth.github import GitHubProvider
from app.auth.oidc import OIDCProvider
from app.config import Settings

# Placeholder values shipped in config defaults / .env.example (including
# the one docker-compose.dev.yml injects for the dev stack) means the
# OAuth-state cookie is signed with a key every reader of the repo knows —
# an attacker can forge the state and drive CSRF through the OAuth
# round-trip. Refuse to boot instead, same posture as the dev-provider
# guard below.
_PLACEHOLDER_SIGNING_KEYS = frozenset(
    {"dev-signing-key-change-me", "dev-signing-key-not-for-prod", "change-me", ""}
)

# Providers that actually run an OAuth round-trip and therefore need the
# state cookie's signature to mean something. "dev" bypasses OAuth entirely
# (see app/auth/dev.py) so a placeholder key there is not a CSRF hole — it's
# the documented local-testing default.
_PROVIDERS_REQUIRING_REAL_SIGNING_KEY = frozenset({"github", "oidc"})


def make_provider(settings: Settings, oauth: OAuth) -> AuthProvider:
    """Build the configured auth provider.

    Extending: add a new branch and a new module under `app/auth/`.
    """
    name = (settings.auth_provider or "").strip().lower()
    signing_key_is_placeholder = (
        settings.session_signing_key.strip() in _PLACEHOLDER_SIGNING_KEYS
    )

    # Refuse a placeholder key for any real IdP regardless of
    # SESSION_COOKIE_SECURE. The previous guard only fired when that flag
    # was true, which meant a deployment that terminates TLS in front of
    # the backend without ever setting SESSION_COOKIE_SECURE=true (or one
    # that plain forgot to) could ship the well-known default key straight
    # through GitHub/OIDC login. AUTH_PROVIDER=dev is exempt on purpose —
    # local dev must keep working with the shipped default.
    if name in _PROVIDERS_REQUIRING_REAL_SIGNING_KEY and signing_key_is_placeholder:
        raise RuntimeError(
            f"SESSION_SIGNING_KEY is still a placeholder value while "
            f"AUTH_PROVIDER={name!r} (a real IdP). The key signs the OAuth "
            "state cookie; a publicly-known key lets an attacker forge it and "
            "drive CSRF through the OAuth round-trip. This is refused "
            "regardless of SESSION_COOKIE_SECURE. Generate a real key with "
            "`openssl rand -hex 32` and set SESSION_SIGNING_KEY before booting."
        )

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
            require_email_verified=settings.oidc_require_email_verified,
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
        return DevAuthProvider(
            settings.dev_admin_email,
            settings.dev_admin_name,
            public_url=settings.public_url,
        )
    raise RuntimeError(
        f"Unknown AUTH_PROVIDER={settings.auth_provider!r}. "
        "Expected 'github', 'oidc', or 'dev'."
    )
