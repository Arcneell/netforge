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

    # Public URL (used to build OIDC redirect URIs)
    public_url: str = "http://localhost:8000"

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://netforge:dev@localhost:5432/netforge"
    )

    # Entra ID
    entra_tenant_id: str = ""
    entra_client_id: str = ""
    entra_client_secret: str = ""

    # Sessions
    session_signing_key: str = "dev-signing-key-change-me"
    session_cookie_name: str = "netforge_session"
    session_max_age_seconds: int = 60 * 60 * 8  # 8h sliding

    # Bootstrap
    bootstrap_admin_email: str = ""

    # Observability
    log_level: str = "info"

    # CORS (comma-separated origin list)
    cors_origins: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def database_url_sync(self) -> str:
        """Sync version of DATABASE_URL (used by Alembic)."""
        return self.database_url.replace("+asyncpg", "")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
