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
    # Which provider to use. One of: "github", "oidc", "dev".
    # Adding a new IdP usually means picking "oidc" and pointing OIDC_ISSUER_URL
    # at it (Keycloak, Authentik, Entra ID, Google Workspace, GitLab, ...).
    # "dev" bypasses OAuth entirely and logs in a fixed admin user — local
    # testing only, refuses to start when SESSION_COOKIE_SECURE is true.
    auth_provider: str = "github"

    # Dev-only fake user surfaced by the "dev" provider. Ignored otherwise.
    dev_admin_email: str = "admin@example.com"
    dev_admin_name: str = "Dev Admin"

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
    # OIDC encodes "the IdP verified this email" in the boolean
    # `email_verified` claim. On a permissive IdP (multi-tenant Entra,
    # public Google, self-service Keycloak realm) an attacker can
    # register an account with an arbitrary email and — combined with
    # JIT user creation + BOOTSTRAP_ADMIN_EMAIL — JIT-promote themselves
    # to admin. We refuse logins whose email is not verified by the IdP.
    # Set to False only if your IdP does not emit the claim AND you trust
    # every email it asserts (e.g. a single-tenant corporate Entra).
    oidc_require_email_verified: bool = True

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

    # ------------------------------------------------------------------
    # Outbound webhooks
    # ------------------------------------------------------------------
    # Webhook URLs are admin-supplied. By default the backend refuses to
    # dispatch to private / loopback / cloud-metadata IPs — see
    # `app/utils/ssrf.py`. Flip this to True ONLY when the backend
    # genuinely needs to hit a private target (a relay on the same
    # docker network, a dev box on localhost). Production deployments
    # should leave it False.
    webhook_allow_private_targets: bool = False
    # Optional shared secret used to HMAC-sign AI scheduler webhook payloads
    # (X-Netforge-Signature header). Empty = payloads are sent unsigned.
    ai_webhook_signing_secret: str = ""
    # Background catch-up sweep for `webhook_outbox` rows that the fast
    # dispatch path (post-commit, in-process) never marked `dispatched_at`
    # for — see `services/webhooks.py::_sweep_outbox_once`. Mirrors
    # `ai_scheduler_enabled` below: disable to keep the fast path (and the
    # durable outbox write itself) working, just without the retry loop.
    webhook_outbox_sweep_enabled: bool = True

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------
    # Cap write methods (POST/PUT/PATCH/DELETE) per IP per window. Defaults
    # are generous enough for normal admin use and tight enough to stop a
    # runaway script.
    rate_limit_writes_per_window: int = 60
    rate_limit_window_seconds: int = 60

    # Where the counters live. "database" (default) keeps them in the
    # `rate_limit_counters` table so every uvicorn worker and every replica
    # shares one budget — without it the effective cap is (workers x limit)
    # and a restart hands every user a fresh AI quota. "memory" restores the
    # legacy per-process sliding window: no extra DB round trip per write,
    # correct only on a single-worker, single-replica deployment.
    # Applies to both limiters (write-per-IP and AI-per-user).
    rate_limit_store: str = "database"

    # Trusted reverse-proxy networks. The backend only honours `X-Real-IP`
    # when the immediate TCP peer matches one of these CIDRs — otherwise
    # an attacker can spoof the header to bypass per-IP rate limits and
    # poison `audit_log.ip_address` / `sessions.ip_address`. Default
    # covers loopback (single uvicorn behind nginx on the same host) and
    # the standard docker-compose bridge subnet (172.16.0.0/12). For
    # deployments with an external LB or sidecar proxy, add that
    # subnet/IP here.
    trusted_proxies: str = "127.0.0.1/32,::1/128,172.16.0.0/12"

    # ------------------------------------------------------------------
    # AI integration (provider-agnostic; see app/services/ai)
    # ------------------------------------------------------------------
    # Master switch — when false, AI routes return 404 and the UI hides
    # every "AI" affordance. Lets self-hosters opt out cleanly.
    ai_enabled: bool = False
    # Which provider implementation to use. One of: "anthropic", "openai",
    # "gemini". Defaults to anthropic — only one with a concrete impl in
    # Phase 1; the others raise a clear "not implemented yet" error.
    ai_provider: str = "anthropic"
    # Optional model override (else each provider picks a sensible default).
    # Anthropic: claude-sonnet-4-6, OpenAI: gpt-4o, Gemini: gemini-2.5-pro.
    ai_model: str = ""
    # API keys — only the one matching `ai_provider` is read. Leaving the
    # others empty is fine.
    ai_anthropic_api_key: str = ""
    ai_openai_api_key: str = ""
    ai_gemini_api_key: str = ""
    # Per-user cap on AI calls in `ai_rate_window_seconds` — defaults to 20
    # calls/hour, which is generous for interactive use and tight enough to
    # stop a runaway script from burning credits.
    ai_rate_limit_calls: int = 20
    ai_rate_window_seconds: int = 3600
    # Soft cap on output tokens per call. Keeps a "give me the full audit
    # log please" prompt from running away to 100k tokens of output.
    ai_max_output_tokens: int = 2048

    # ------------------------------------------------------------------
    # Granular feature toggles. All default to True, gated by the master
    # `ai_enabled` flag above. Flip individual flags to False to keep some
    # AI features but disable others — useful when a compliance or risk
    # review only signs off on a subset.
    #
    # Features always-available (no toggle) regardless of `ai_enabled`:
    #   - GET /api/ai/integrity-checks (deterministic SQL, no LLM call)
    # ------------------------------------------------------------------
    # NL-to-action drafts (`POST /api/ai/drafts` + apply / reject). Highest
    # risk surface because applying a draft mutates inventory rows. Disable
    # if your org wants to keep the LLM read-only.
    ai_drafts_enabled: bool = True
    # Background scheduler (periodic advisor / suggest-links + webhook
    # notification). Disable to keep the AI features available manually but
    # never auto-fire.
    ai_scheduler_enabled: bool = True

    # ------------------------------------------------------------------
    # CSV import
    # ------------------------------------------------------------------
    # Hard cap on data rows per CSV (header excluded). `BULK_MAX_TOTAL_BYTES`
    # already bounds upload *weight*, but a pathological file (e.g. a huge
    # number of very short rows) could still stay under that byte cap while
    # producing hundreds of thousands of rows — each one a resolver lookup
    # plus a flush/SAVEPOINT round trip. Refused with a clean 400 rather than
    # a slow request or an OOM.
    csv_import_max_rows: int = 50_000

    # ------------------------------------------------------------------
    # Audit log retention
    # ------------------------------------------------------------------
    # Days after which `audit_log` rows are purged, mirroring the rolling
    # windows already applied to `webhook_deliveries` (services/webhooks.py)
    # and `ai_run_logs` (services/ai/scheduler.py). 0 (default) disables the
    # purge — unlike those two tables, an audit trail is exactly the data an
    # operator would NOT want silently aged out, so unlimited retention is
    # the conservative default. Set to e.g. 365 to cap disk growth once you
    # know your compliance/retention policy.
    audit_log_retention_days: int = 0

    # Observability
    log_level: str = "info"
    # "text" (default, human-readable) or "json" (one JSON object per line for
    # log aggregators). JSON mode carries the request id + structured fields.
    log_format: str = "text"

    # CORS (comma-separated origin list)
    cors_origins: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
