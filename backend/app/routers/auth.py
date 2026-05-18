"""Authentication endpoints: /login, /callback, /logout, /me.

The login flow:

1. The SPA sends the user to `GET /api/auth/login`.
2. The backend builds the authorize URL and 302s the browser to the IdP.
3. The IdP redirects back to `GET /api/auth/callback?code=...&state=...`.
4. The backend exchanges the code, JIT-upserts the user, creates a DB
   session, sets the `netforge_session` cookie, and 302s to the SPA root.
5. The SPA pulls the current user from `GET /api/auth/me`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.base import AuthProvider
from app.auth.dependencies import get_current_user, get_provider
from app.auth.sessions import (
    clear_session_cookie,
    create_session,
    delete_session,
    get_session_id_from_cookie,
    set_session_cookie,
)
from app.config import Settings, get_settings
from app.db import get_session as get_db_session
from app.models.user import User
from app.schemas.api_token import ApiTokenCreate, ApiTokenCreated, ApiTokenRead
from app.services import api_tokens as token_service
from app.services.users import upsert_user_from_provider

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login")
async def login(
    request: Request,
    provider: AuthProvider = Depends(get_provider),
    settings: Settings = Depends(get_settings),
) -> Response:
    redirect_uri = f"{settings.public_url.rstrip('/')}/api/auth/callback"
    return await provider.authorize_redirect(request, redirect_uri)


@router.get("/callback", name="auth_callback")
async def callback(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    provider: AuthProvider = Depends(get_provider),
    settings: Settings = Depends(get_settings),
) -> Response:
    info = await provider.authenticate(request)
    user = await upsert_user_from_provider(db, provider.name, info, settings)
    session = await create_session(db, user, request, settings)

    # Send the user back to the SPA root; the SPA fetches /api/auth/me next.
    response = RedirectResponse(url="/", status_code=302)
    set_session_cookie(response, session.id, settings)
    return response


@router.post("/logout")
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    session_id = get_session_id_from_cookie(request, settings)
    if session_id:
        await delete_session(db, session_id)
    response = JSONResponse({"ok": True})
    clear_session_cookie(response, settings)
    return response


@router.get("/me")
async def me(user: User = Depends(get_current_user)) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role.value,
        "provider": user.provider,
    }


# --- API tokens ---------------------------------------------------------- #


@router.get("/tokens", response_model=list[ApiTokenRead])
async def list_my_tokens(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[ApiTokenRead]:
    """Tokens owned by the calling user, most recent first. Includes revoked
    rows so the user can audit what was issued historically."""
    tokens = await token_service.list_tokens(db, user)
    return [ApiTokenRead.model_validate(t) for t in tokens]


@router.post(
    "/tokens",
    response_model=ApiTokenCreated,
    status_code=201,
)
async def create_my_token(
    payload: ApiTokenCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ApiTokenCreated:
    """Mint a new API token for the calling user. The plaintext is returned
    **once** in the response body — never again. The token inherits the
    caller's role, so demoting / disabling the user immediately limits what
    the token can do."""
    row, plaintext = await token_service.create_token(
        db, user, name=payload.name, expires_at=payload.expires_at
    )
    return ApiTokenCreated(
        **ApiTokenRead.model_validate(row).model_dump(),
        token=plaintext,
    )


@router.delete("/tokens/{token_id}", status_code=204)
async def revoke_my_token(
    token_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Revoke a token. Idempotent on already-revoked tokens — only returns
    404 if the id is unknown or owned by someone else."""
    await token_service.revoke_token(db, user, token_id)
