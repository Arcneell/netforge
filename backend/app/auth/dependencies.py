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
from app.models.user import ApiTokenScope, User, UserRole

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


def _bearer_token_from_header(request: Request) -> str | None:
    """Extract the token from an ``Authorization: Bearer <token>`` header,
    case-insensitive on the scheme so curl's default lowercase still works."""
    header = request.headers.get("authorization")
    if not header:
        return None
    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> User:
    """Resolve the current user from a session cookie or an API token.

    Order: Bearer header first (so a script doesn't accidentally land in the
    UI's session if it sets both), then the session cookie. 401 otherwise.
    """
    user: User | None = None

    bearer = _bearer_token_from_header(request)
    if bearer:
        from app.services import api_tokens as token_service

        result = await token_service.verify_token(db, bearer)
        if result is None:
            raise _auth_required()
        user, scope = result
        if scope is ApiTokenScope.read_only:
            user = _capped_to_viewer(user)
    else:
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

    # Make the user id visible to the audit-log SQLAlchemy listeners.
    from app.services.audit import current_user_id_var

    current_user_id_var.set(user.id)

    return user


def _capped_to_viewer(user: User) -> User:
    """Return a transient copy of `user` with its role forced to viewer.

    Used for requests authenticated by a `read_only` API token: the effective
    role must drop to viewer for THIS request only, so every existing
    `require_role(...)` check downstream rejects writes without any change
    on its part. The copy is a brand-new, never-added-to-a-session `User`
    instance — it is never attached to `db`, so nothing about it can ever be
    flushed. The real row (and the real user's real role) is untouched.
    """
    return User(
        id=user.id,
        provider=user.provider,
        subject=user.subject,
        email=user.email,
        display_name=user.display_name,
        role=UserRole.viewer,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


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
