"""Tests for app.auth.factory.make_provider."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from authlib.integrations.starlette_client import OAuth
from fastapi import HTTPException

from app.auth.dev import DevAuthProvider
from app.auth.factory import make_provider
from app.auth.github import GitHubProvider
from app.auth.oidc import OIDCProvider
from app.config import Settings


def test_make_provider_github() -> None:
    settings = Settings(
        auth_provider="github",
        github_client_id="id",
        github_client_secret="secret",
    )
    provider = make_provider(settings, OAuth())
    assert isinstance(provider, GitHubProvider)
    assert provider.name == "github"


def test_make_provider_oidc() -> None:
    settings = Settings(
        auth_provider="oidc",
        oidc_issuer_url="https://idp.example.com",
        oidc_client_id="id",
        oidc_client_secret="secret",
    )
    provider = make_provider(settings, OAuth())
    assert isinstance(provider, OIDCProvider)
    assert provider.name == "oidc"


def test_make_provider_rejects_unknown_name() -> None:
    settings = Settings(auth_provider="ldap")
    with pytest.raises(RuntimeError, match="Unknown AUTH_PROVIDER"):
        make_provider(settings, OAuth())


def test_make_provider_github_requires_credentials() -> None:
    settings = Settings(auth_provider="github", github_client_id="", github_client_secret="")
    with pytest.raises(RuntimeError, match="GitHub"):
        make_provider(settings, OAuth())


def test_make_provider_oidc_requires_issuer() -> None:
    settings = Settings(
        auth_provider="oidc",
        oidc_issuer_url="",
        oidc_client_id="id",
        oidc_client_secret="secret",
    )
    with pytest.raises(RuntimeError, match="OIDC"):
        make_provider(settings, OAuth())


def test_make_provider_is_case_insensitive() -> None:
    settings = Settings(
        auth_provider="GitHub",
        github_client_id="id",
        github_client_secret="secret",
    )
    provider = make_provider(settings, OAuth())
    assert provider.name == "github"


def test_make_provider_dev() -> None:
    settings = Settings(
        auth_provider="dev",
        dev_admin_email="me@example.test",
        dev_admin_name="Me",
        session_cookie_secure=False,
    )
    provider = make_provider(settings, OAuth())
    assert isinstance(provider, DevAuthProvider)
    assert provider.name == "dev"


def test_make_provider_dev_refuses_secure_cookies() -> None:
    # SESSION_COOKIE_SECURE=true is the strongest "this is production" signal
    # we have — the factory must refuse to hand out a passwordless admin login.
    settings = Settings(auth_provider="dev", session_cookie_secure=True)
    with pytest.raises(RuntimeError, match="SESSION_COOKIE_SECURE"):
        make_provider(settings, OAuth())


def test_make_provider_dev_refuses_non_loopback_public_url() -> None:
    """Belt-and-suspenders to the SESSION_COOKIE_SECURE guard: if
    PUBLIC_URL points anywhere that isn't a loopback host, the dev
    bypass is reachable from the LAN/public internet. Each hit on
    /api/auth/login creates an admin session, so the dev provider
    must refuse to start in that configuration.
    """
    settings = Settings(
        auth_provider="dev",
        session_cookie_secure=False,
        public_url="http://192.168.1.42:8000",
    )
    with pytest.raises(RuntimeError, match="loopback"):
        make_provider(settings, OAuth())


def _oidc_with_userinfo(userinfo: dict, *, require_email_verified: bool = True) -> OIDCProvider:
    """Build a real OIDCProvider but stub authlib so authenticate() returns
    `userinfo`. We need a real instance because the email_verified guard
    lives in `OIDCProvider.authenticate`, not in the factory.
    """
    oauth = OAuth()
    provider = OIDCProvider(
        oauth,
        issuer_url="https://idp.example.com",
        client_id="id",
        client_secret="secret",
        require_email_verified=require_email_verified,
    )
    fake_client = MagicMock()
    fake_client.authorize_access_token = AsyncMock(return_value={"userinfo": userinfo})
    provider._oauth.oidc = fake_client  # type: ignore[attr-defined]
    return provider


@pytest.mark.asyncio
async def test_oidc_refuses_unverified_email_when_strict() -> None:
    """A permissive IdP (multi-tenant Entra, public Google, self-service
    Keycloak realm) lets an attacker register with an arbitrary email.
    Combined with JIT user creation + BOOTSTRAP_ADMIN_EMAIL, that's an
    admin-promotion path. Refuse the login when `email_verified` is
    missing / false / falsy-string.
    """
    provider = _oidc_with_userinfo(
        {"sub": "x", "email": "victim@example.com", "email_verified": False}
    )
    with pytest.raises(HTTPException) as exc:
        await provider.authenticate(MagicMock())
    assert exc.value.status_code == 400
    assert exc.value.detail["error"]["code"] == "AUTH_EMAIL_NOT_VERIFIED"


@pytest.mark.asyncio
async def test_oidc_refuses_missing_email_verified_claim_when_strict() -> None:
    """Some IdPs omit the claim entirely — strict mode treats that as
    not-verified, since trusting an unverified email is the same risk
    whether the IdP said `false` or said nothing."""
    provider = _oidc_with_userinfo({"sub": "x", "email": "v@example.com"})
    with pytest.raises(HTTPException) as exc:
        await provider.authenticate(MagicMock())
    assert exc.value.detail["error"]["code"] == "AUTH_EMAIL_NOT_VERIFIED"


@pytest.mark.asyncio
async def test_oidc_coerces_string_email_verified() -> None:
    """Some IdPs (notably older Keycloak builds) emit the claim as a
    string. The guard must coerce so a literal `"true"` is accepted and
    `"false"` is rejected — without this, every login from those IdPs
    would 400 even when the email was verified."""
    ok = _oidc_with_userinfo(
        {"sub": "x", "email": "ok@example.com", "email_verified": "true"}
    )
    info = await ok.authenticate(MagicMock())
    assert info.email == "ok@example.com"

    not_ok = _oidc_with_userinfo(
        {"sub": "x", "email": "ko@example.com", "email_verified": "false"}
    )
    with pytest.raises(HTTPException):
        await not_ok.authenticate(MagicMock())


@pytest.mark.asyncio
async def test_oidc_allows_unverified_when_opted_out() -> None:
    """Operators with a known-good IdP that doesn't emit the claim can
    set OIDC_REQUIRE_EMAIL_VERIFIED=false. In that mode the guard is
    skipped — pin the opt-out so the setting is wired all the way through.
    """
    provider = _oidc_with_userinfo(
        {"sub": "x", "email": "x@example.com"},
        require_email_verified=False,
    )
    info = await provider.authenticate(MagicMock())
    assert info.email == "x@example.com"


def test_make_provider_dev_accepts_loopback_public_urls() -> None:
    """Loopback variants we explicitly accept: localhost, 127.0.0.1,
    ::1, 0.0.0.0 (the last for the docker-compose case where the
    container binds 0.0.0.0 but is mapped to 127.0.0.1 on the host).
    Each must produce a working DevAuthProvider with no raise.
    """
    for url in (
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://[::1]:8000",
        "http://0.0.0.0:8000",
    ):
        settings = Settings(
            auth_provider="dev", session_cookie_secure=False, public_url=url
        )
        assert isinstance(make_provider(settings, OAuth()), DevAuthProvider), url
