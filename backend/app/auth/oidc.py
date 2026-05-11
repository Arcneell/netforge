"""Generic OIDC provider.

Works with any IdP that publishes `.well-known/openid-configuration` and
returns an ID token with at least the `sub` and `email` claims.

Tested against: Entra ID, Keycloak, Authentik, Google Workspace, GitLab.
"""

from __future__ import annotations

from authlib.integrations.starlette_client import OAuth
from fastapi import HTTPException, Request, Response, status

from app.auth.base import AuthProvider, UserInfo


class OIDCProvider(AuthProvider):
    name = "oidc"

    def __init__(
        self,
        oauth: OAuth,
        issuer_url: str,
        client_id: str,
        client_secret: str,
        scope: str = "openid email profile",
    ) -> None:
        if not issuer_url or not client_id or not client_secret:
            raise RuntimeError(
                "OIDC provider requires OIDC_ISSUER_URL, OIDC_CLIENT_ID and OIDC_CLIENT_SECRET"
            )
        oauth.register(
            name="oidc",
            client_id=client_id,
            client_secret=client_secret,
            server_metadata_url=f"{issuer_url.rstrip('/')}/.well-known/openid-configuration",
            client_kwargs={"scope": scope},
        )
        self._oauth = oauth

    async def authorize_redirect(self, request: Request, redirect_uri: str) -> Response:
        return await self._oauth.oidc.authorize_redirect(request, redirect_uri)

    async def authenticate(self, request: Request) -> UserInfo:
        token = await self._oauth.oidc.authorize_access_token(request)

        # authlib parses the ID token and exposes the claims as token["userinfo"]
        # when `openid` is in the scope. Fall back to /userinfo otherwise.
        userinfo = token.get("userinfo")
        if userinfo is None:
            userinfo = await self._oauth.oidc.userinfo(token=token)

        subject = userinfo.get("sub")
        email = userinfo.get("email")
        if not subject or not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": {
                        "code": "AUTH_INVALID_CLAIMS",
                        "message": "OIDC userinfo is missing `sub` or `email`.",
                    }
                },
            )

        return UserInfo(
            subject=str(subject),
            email=email,
            display_name=userinfo.get("name") or userinfo.get("preferred_username"),
        )
