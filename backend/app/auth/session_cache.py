"""Optional Redis cache for the resolved (session -> user) pair.

Why this exists
---------------
`get_current_user` costs two SELECTs on *every* authenticated request: one on
`sessions` to find the row and check it is live, one on `users` to load the
principal. Nothing else on the request path is paid that unconditionally —
a GET on `/api/sites` is three queries, two of which are this. On a page load
that fires six parallel GETs, that is twelve queries spent re-deriving an
answer that cannot have changed in the interval.

What is cached
--------------
The columns `require_role` and the audit listeners actually read, plus the
session's own `expires_at` so the cache can enforce expiry without asking
Postgres. The value is keyed by the SHA-256 digest of the cookie — never by
the cookie itself, exactly like the `sessions` table (see `sessions.py`). A
Redis dump is therefore no more replayable than a DB dump: the digest is
useless without its preimage.

SECURITY — what this trades away
--------------------------------
`sessions` is a table rather than a JWT specifically so revocation is
immediate: delete the row and the next request is anonymous. Caching the
lookup puts a window in front of that. Three things bound it:

1. **Explicit eviction.** `sessions.delete_session` (logout) drops the key in
   the same call that deletes the row, so the documented revocation path stays
   immediate.
2. **A short TTL.** `CACHE_SESSION_TTL_SECONDS` defaults to 30s, which is
   already enough to absorb the burst of parallel GETs one page load fires
   while capping how long *any* revocation path we did not wire explicitly
   (an admin editing `users.role` directly in psql, a row deleted by hand)
   can be served stale.
3. **No caching near expiry.** An entry is only written while the session has
   more than `sessions._RENEW_THRESHOLD` left on its clock — see
   `_is_cacheable`. This keeps sliding renewal (`touch_session`, which only
   fires inside that threshold and which a cache hit would skip) working
   exactly as it does without Redis, and means a cached entry can never
   outlive the session it describes.

Bearer tokens are deliberately NOT cached. `api_tokens.verify_token` writes
`last_used_at` on every call — an admin-visible signal we would be throwing
away — and a revoked token needs to stop working now, not in 30s. Scripts
polling with a token are also far less latency-sensitive than the SPA, which
is what this cache is for.

Every failure here is a miss: the caller falls through to Postgres and the
request behaves exactly as it would with `REDIS_URL` unset.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.config import Settings
from app.models.user import User, UserRole

logger = logging.getLogger("netforge.cache")

# Bumped when the cached shape changes. An entry written by a previous
# revision then decodes to None instead of a User missing a field.
_SCHEMA_VERSION = 1


def _key(session_id_hash: str) -> str:
    return f"sess:v{_SCHEMA_VERSION}:{session_id_hash}"


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    # Rows come back from asyncpg as timezone-aware; a naive value here would
    # blow up the comparison in `get_principal`. Assume UTC, which is what
    # every timestamp in this codebase is stored as.
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


async def get_principal(session_id_hash: str, settings: Settings) -> User | None:
    """The cached principal for this session digest, or None on any miss.

    The returned `User` is transient: built by hand, never added to a
    `Session`, so nothing about it can be flushed. Same shape as the copy
    `dependencies._capped_to_viewer` hands to `read_only` token requests.
    """
    if not settings.cache_sessions_enabled:
        return None
    from app import cache

    payload = await cache.get_json(_key(session_id_hash))
    if not isinstance(payload, dict):
        return None

    expires_at = _parse_datetime(payload.get("session_expires_at"))
    if expires_at is None or expires_at <= datetime.now(UTC):
        # Belt and braces: the TTL should have retired this already (entries
        # are never written with a TTL past the session's own expiry). Treat a
        # survivor as a miss rather than honouring an expired session.
        return None

    try:
        role = UserRole(payload["role"])
        return User(
            id=int(payload["id"]),
            provider=payload["provider"],
            subject=payload["subject"],
            email=payload["email"],
            display_name=payload["display_name"],
            role=role,
            last_login_at=_parse_datetime(payload.get("last_login_at")),
            created_at=_parse_datetime(payload.get("created_at")),
        )
    except (KeyError, TypeError, ValueError):
        logger.warning("cache.session.malformed — treating as a miss")
        return None


async def store_principal(
    session_id_hash: str,
    user: User,
    session_expires_at: datetime,
    settings: Settings,
) -> None:
    """Cache `user` for this session digest. Best effort, never raises."""
    if not settings.cache_sessions_enabled:
        return
    ttl = _ttl_for(session_expires_at, settings)
    if ttl <= 0:
        return
    from app import cache

    await cache.set_json(
        _key(session_id_hash),
        {
            "id": user.id,
            "provider": user.provider,
            "subject": user.subject,
            "email": user.email,
            "display_name": user.display_name,
            "role": user.role.value,
            "last_login_at": _isoformat(user.last_login_at),
            "created_at": _isoformat(user.created_at),
            "session_expires_at": _isoformat(session_expires_at),
        },
        ttl_seconds=ttl,
    )


async def invalidate(session_id_hash: str) -> None:
    """Drop the entry for this session digest. Called on logout / deletion."""
    from app import cache

    await cache.delete(_key(session_id_hash))


def _ttl_for(session_expires_at: datetime, settings: Settings) -> int:
    """Seconds to cache for: the configured TTL, clamped so an entry can never
    outlive the session it describes, and 0 when the session is close enough to
    expiry that `touch_session` needs to run on every request."""
    if not _is_cacheable(session_expires_at):
        return 0
    remaining = int((session_expires_at - datetime.now(UTC)).total_seconds())
    return max(0, min(settings.cache_session_ttl_seconds, remaining))


def _is_cacheable(session_expires_at: datetime) -> bool:
    """False once the session enters its sliding-renewal window.

    A cache hit skips `touch_session`, so caching inside the renewal window
    would delay (or, at the very end of a session, skip) the renewal that keeps
    an active user logged in. Outside that window `touch_session` is a no-op
    anyway, so there is nothing to lose by caching — see the module docstring.
    """
    from app.auth.sessions import _RENEW_THRESHOLD

    return session_expires_at - datetime.now(UTC) > _RENEW_THRESHOLD


__all__ = ["get_principal", "invalidate", "store_principal"]
