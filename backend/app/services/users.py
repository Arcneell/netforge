"""User service — JIT upsert from external provider identity.

Promotion rules on first sight of a user:

- If `BOOTSTRAP_ADMIN_EMAIL` is set and matches the email, → admin.
- Otherwise, if no user exists yet in the database (cold start), → admin.
- Otherwise, → viewer. An existing admin must promote them manually.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.base import UserInfo
from app.config import Settings
from app.models.user import User, UserRole


async def upsert_user_from_provider(
    db: AsyncSession,
    provider: str,
    info: UserInfo,
    settings: Settings,
) -> User:
    """Find-or-create a `User` keyed on `(provider, subject)`."""
    result = await db.execute(
        select(User).where(User.provider == provider, User.subject == info.subject)
    )
    user = result.scalar_one_or_none()

    if user is None:
        role = await _initial_role(db, info.email, settings)
        user = User(
            provider=provider,
            subject=info.subject,
            email=info.email,
            display_name=info.display_name,
            role=role,
        )
        db.add(user)
    else:
        # Email / name may have changed at the IdP — keep our copy in sync.
        user.email = info.email
        user.display_name = info.display_name

    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)
    return user


async def _initial_role(
    db: AsyncSession, email: str, settings: Settings
) -> UserRole:
    bootstrap = (settings.bootstrap_admin_email or "").strip().lower()
    if bootstrap and email.lower() == bootstrap:
        return UserRole.admin
    if await _user_count(db) == 0:
        return UserRole.admin
    return UserRole.viewer


async def _user_count(db: AsyncSession) -> int:
    result = await db.execute(select(func.count()).select_from(User))
    return int(result.scalar() or 0)
