"""GitHub OAuth 2.0 provider.

Note: GitHub does **not** expose an OIDC userinfo endpoint for end-user auth
(its OIDC implementation is for Actions workload identity). We use the REST
API to fetch user info instead.
"""

from __future__ import annotations

from authlib.integrations.starlette_client import OAuth
from fastapi import HTTPException, Request, Response, status

from app.auth.base import AuthProvider, UserInfo


class GitHubProvider(AuthProvider):
    name = "github"

    def __init__(self, oauth: OAuth, client_id: str, client_secret: str) -> None:
        if not client_id or not client_secret:
            raise RuntimeError(
                "GitHub provider requires GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET"
            )
        oauth.register(
            name="github",
            client_id=client_id,
            client_secret=client_secret,
            access_token_url="https://github.com/login/oauth/access_token",
            authorize_url="https://github.com/login/oauth/authorize",
            api_base_url="https://api.github.com/",
            # PKCE (RFC 7636, S256). GitHub's classic OAuth apps don't
            # require it and silently ignore the extra `code_challenge*` /
            # `code_verifier` parameters, but sending it is free defence in
            # depth against authorization-code interception and costs
            # nothing here — authlib generates the verifier, carries it in
            # the same signed `netforge_oauth_state` session cookie already
            # used for the `state` param, and replays it at the token
            # exchange automatically once `code_challenge_method` is set.
            client_kwargs={"scope": "read:user user:email", "code_challenge_method": "S256"},
        )
        self._oauth = oauth

    async def authorize_redirect(self, request: Request, redirect_uri: str) -> Response:
        return await self._oauth.github.authorize_redirect(request, redirect_uri)

    async def authenticate(self, request: Request) -> UserInfo:
        token = await self._oauth.github.authorize_access_token(request)

        user_resp = await self._oauth.github.get("user", token=token)
        user_resp.raise_for_status()
        user = user_resp.json()

        # `user.email` may be null if the user keeps it private. Hit /user/emails
        # for the primary verified address.
        email = user.get("email")
        if not email:
            emails_resp = await self._oauth.github.get("user/emails", token=token)
            emails_resp.raise_for_status()
            emails = emails_resp.json()
            primary = next(
                (e for e in emails if e.get("primary") and e.get("verified")),
                None,
            )
            email = primary["email"] if primary else None

        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": {
                        "code": "AUTH_NO_EMAIL",
                        "message": "GitHub account has no verified primary email.",
                    }
                },
            )

        return UserInfo(
            subject=str(user["id"]),
            email=email,
            display_name=user.get("name") or user.get("login"),
        )
