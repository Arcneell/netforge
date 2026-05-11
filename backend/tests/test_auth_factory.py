"""Tests for app.auth.factory.make_provider."""

import pytest
from authlib.integrations.starlette_client import OAuth

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
