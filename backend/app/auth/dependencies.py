"""FastAPI dependencies for authentication and authorization."""

from __future__ import annotations

from authlib.integrations.starlette_client import OAuth
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.base import AuthProvider
from app.auth.factory import make_provider
from app.auth.sessions import (
    get_active_session,
    get_session_id_from_cookie,
    touch_session,
)
from app.config import Settings, get_settings
from app.db import get_session as get_db_session
from app.models.user import User, UserRole

# Module-level singletons: the authlib OAuth registry and the configured
# provider are built once at first use.
_oauth: OAuth | None = None
_provider: AuthProvider | None = None


def _get_oauth() -> OAuth:
    global _oauth
    if _oauth is None:
        _oauth = OAuth()
    return _oauth


def get_provider(settings: Settings = Depends(get_settings)) -> AuthProvider:
    global _provider
    if _provider is None:
        _provider = make_provider(settings, _get_oauth())
    return _provider


def _auth_required() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": {"code": "AUTH_REQUIRED"}},
    )


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> User:
    """Resolve the current user from the session cookie. 401 otherwise."""
    session_id = get_session_id_from_cookie(request, settings)
    if not session_id:
        raise _auth_required()

    session = await get_active_session(db, session_id)
    if session is None:
        raise _auth_required()

    user = await db.get(User, session.user_id)
    if user is None:
        # Session points at a deleted user — treat as logged out.
        raise _auth_required()

    await touch_session(db, session, settings)
    return user


def require_role(*roles: UserRole):
    """Build a dependency that allows only users with one of the given roles."""

    async def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": {"code": "FORBIDDEN"}},
            )
        return user

    return _dep


def reset_provider_cache() -> None:
    """Test hook — clears the cached OAuth registry and provider."""
    global _oauth, _provider
    _oauth = None
    _provider = None
