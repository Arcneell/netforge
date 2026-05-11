"""Environment-backed settings (see .env.example)."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Public URL (used to build OAuth/OIDC redirect URIs)
    public_url: str = "http://localhost:8000"

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://netforge:dev@localhost:5432/netforge"
    )

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------
    # Which provider to use. One of: "github", "oidc".
    # Adding a new IdP usually means picking "oidc" and pointing OIDC_ISSUER_URL
    # at it (Keycloak, Authentik, Entra ID, Google Workspace, GitLab, ...).
    auth_provider: str = "github"

    # GitHub OAuth 2.0 (https://github.com/settings/developers)
    github_client_id: str = ""
    github_client_secret: str = ""

    # Generic OIDC provider
    # OIDC_ISSUER_URL is the base URL exposing /.well-known/openid-configuration.
    # For Entra ID: https://login.microsoftonline.com/<tenant-id>/v2.0
    # For Keycloak: https://<host>/realms/<realm>
    oidc_issuer_url: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_scope: str = "openid email profile"

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------
    # Signs the short-lived Starlette session used during the OAuth round-trip
    # (stores the OAuth `state` parameter). Generate with: openssl rand -hex 32.
    session_signing_key: str = "dev-signing-key-change-me"
    # Cookie name holding the long-lived netforge session id.
    session_cookie_name: str = "netforge_session"
    # Sliding lifetime, in seconds.
    session_max_age_seconds: int = 60 * 60 * 8  # 8h
    # Set to True in production (HTTPS only). Leave False for local HTTP dev.
    session_cookie_secure: bool = False

    # Bootstrap: the first user matching this email is promoted to admin on first login.
    # Empty string disables this — only the very first user to log in becomes admin.
    bootstrap_admin_email: str = ""

    # Observability
    log_level: str = "info"

    # CORS (comma-separated origin list)
    cors_origins: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
