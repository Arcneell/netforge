"""PKCE (RFC 7636, S256) wiring for the OAuth providers.

Both `GitHubProvider` and `OIDCProvider` register their authlib client with
`code_challenge_method: "S256"` in `client_kwargs`. authlib's OAuth2 client
takes it from there: it generates the `code_verifier`, carries it through
the same signed `netforge_oauth_state` session cookie already used for
`state`/`nonce` (see `authlib.integrations.starlette_client`), and replays
it at the token exchange — no extra plumbing needed on our side. These
tests pin that the registration actually turns PKCE on; the ecosystem
mechanics themselves are authlib's responsibility, not ours to re-test.
"""

from __future__ import annotations

from authlib.integrations.starlette_client import OAuth

from app.auth.github import GitHubProvider
from app.auth.oidc import OIDCProvider


def test_github_provider_enables_pkce() -> None:
    oauth = OAuth()
    GitHubProvider(oauth, client_id="id", client_secret="secret")
    assert oauth.github.client_kwargs.get("code_challenge_method") == "S256"


def test_oidc_provider_enables_pkce() -> None:
    oauth = OAuth()
    OIDCProvider(
        oauth,
        issuer_url="https://idp.example.com",
        client_id="id",
        client_secret="secret",
    )
    assert oauth.oidc.client_kwargs.get("code_challenge_method") == "S256"


def test_github_provider_keeps_its_scope_alongside_pkce() -> None:
    """Regression: adding code_challenge_method must not clobber the
    existing `scope` client_kwarg GitHub needs to read the user's email."""
    oauth = OAuth()
    GitHubProvider(oauth, client_id="id", client_secret="secret")
    assert oauth.github.client_kwargs.get("scope") == "read:user user:email"


def test_oidc_provider_keeps_its_scope_alongside_pkce() -> None:
    oauth = OAuth()
    OIDCProvider(
        oauth,
        issuer_url="https://idp.example.com",
        client_id="id",
        client_secret="secret",
        scope="openid email profile groups",
    )
    assert oauth.oidc.client_kwargs.get("scope") == "openid email profile groups"
