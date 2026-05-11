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
