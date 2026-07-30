"""User service — JIT upsert from external provider identity.

Promotion rules on first sight of a user:

- If `BOOTSTRAP_ADMIN_EMAIL` is set and matches the email, → admin.
- Otherwise, if no user exists yet in the database (cold start), → admin.
- Otherwise, → viewer. An existing admin must promote them manually.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.base import UserInfo
from app.config import Settings
from app.models.user import User, UserRole

# Stable advisory-lock key for the cold-start admin promotion path. The
# value is arbitrary; what matters is that every backend worker in the
# fleet uses the same int so the lock serialises concurrent first-time
# logins (two browsers hitting /api/auth/callback simultaneously on a
# fresh install both seeing `count == 0` and both becoming admin).
# Postgres advisory-xact locks auto-release at COMMIT/ROLLBACK.
_BOOTSTRAP_LOCK_KEY = 0x6E66_6F72_6765_0001  # "nforge\x00\x01"


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
        # The cold-start admin promotion is the only branch that needs
        # serialising. For every other first-time login (a brand-new
        # user joining an established install, an SSO rollout that
        # creates many users at once) the lock would turn the login
        # path into a serial bottleneck across all workers. Take the
        # lock ONLY when the count is zero AND there's no
        # BOOTSTRAP_ADMIN_EMAIL match — that's the race surface.
        bootstrap = (settings.bootstrap_admin_email or "").strip().lower()
        matches_bootstrap = bool(bootstrap) and info.email.lower() == bootstrap
        if not matches_bootstrap and await _user_count(db) == 0:
            await _acquire_bootstrap_lock(db)
            # Re-check after taking the lock: another worker might have
            # committed the first admin while we waited.
            role = UserRole.admin if await _user_count(db) == 0 else UserRole.viewer
        elif matches_bootstrap:
            role = UserRole.admin
        else:
            role = UserRole.viewer
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

    user.last_login_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(user)
    return user


async def _acquire_bootstrap_lock(db: AsyncSession) -> None:
    """Acquire the cold-start bootstrap advisory lock. Postgres-only;
    non-Postgres backends (test SQLite, future MySQL port) silently
    skip — those deployments don't have the concurrent-request race
    this lock protects against.

    Detection runs against the bind's sync engine because AsyncSession
    exposes the underlying dialect via `sync_session.bind.dialect.name`.
    Anything that doesn't expose a Postgres dialect (mocks, sqlite-in-
    memory test fixtures) falls through without firing the SQL — the
    lock is a belt-and-suspenders guard, never a worse-than-baseline path.
    """
    dialect_name = _dialect_name(db)
    if dialect_name != "postgresql":
        return
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=_BOOTSTRAP_LOCK_KEY)
    )


def _dialect_name(db: AsyncSession) -> str:
    """Best-effort detection of the underlying DB dialect.

    Reads `sync_session.bind.dialect.name` — the public path that
    AsyncSession documents. Returns an empty string for mocks / objects
    that don't expose the chain, which the caller treats as "not
    Postgres" and skips the lock entirely.
    """
    try:
        # `bind` is typed as Engine | Connection | None; a None bind raises
        # AttributeError here, which is exactly the "not Postgres" fallback.
        name = db.sync_session.bind.dialect.name  # type: ignore[union-attr]
    except AttributeError:
        return ""
    return str(name) if isinstance(name, str) else ""


async def _user_count(db: AsyncSession) -> int:
    result = await db.execute(select(func.count()).select_from(User))
    return int(result.scalar() or 0)
