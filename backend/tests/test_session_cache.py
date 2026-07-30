"""Tests for the cached (session -> user) resolution.

The interesting cases are all about *not* trusting the cache too far: an entry
must never outlive its session, must never survive a logout, and must never be
written while the session is inside its sliding-renewal window (where a cache
hit would skip `touch_session` and stall the renewal).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

import pytest

from app import cache
from app.auth import session_cache
from app.config import get_settings
from app.models.user import User, UserRole

from .test_cache import FakeRedis

_DIGEST = "a" * 64


@pytest.fixture
def configure() -> Iterator[Callable[..., FakeRedis]]:
    """Inject a FakeRedis and set the cache-related env vars."""

    def _apply(**env: str) -> FakeRedis:
        client = FakeRedis()
        os.environ["REDIS_URL"] = "redis://localhost:6379/0"
        os.environ["CACHE_KEY_PREFIX"] = "netforge"
        os.environ.update(env)
        get_settings.cache_clear()
        cache._client = client
        cache._client_built = True
        return client

    yield _apply

    for name in (
        "REDIS_URL",
        "CACHE_KEY_PREFIX",
        "CACHE_SESSIONS_ENABLED",
        "CACHE_SESSION_TTL_SECONDS",
    ):
        os.environ.pop(name, None)
    get_settings.cache_clear()
    cache.reset_client()


def _user(role: UserRole = UserRole.admin) -> User:
    return User(
        id=7,
        provider="oidc",
        subject="sub-123",
        email="ops@example.com",
        display_name="Ops Person",
        role=role,
        last_login_at=datetime(2026, 7, 30, 8, 0, tzinfo=UTC),
        created_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )


def _far_future() -> datetime:
    """Well outside the sliding-renewal window, so entries are cacheable."""
    return datetime.now(UTC) + timedelta(hours=8)


# --- Roundtrip ------------------------------------------------------------- #


async def test_store_then_get_returns_an_equivalent_principal(
    configure: Callable[..., FakeRedis],
) -> None:
    configure()
    settings = get_settings()
    original = _user()

    await session_cache.store_principal(_DIGEST, original, _far_future(), settings)
    restored = await session_cache.get_principal(_DIGEST, settings)

    assert restored is not None
    assert (restored.id, restored.email, restored.provider, restored.subject) == (
        original.id,
        original.email,
        original.provider,
        original.subject,
    )
    assert restored.role is UserRole.admin
    assert restored.display_name == original.display_name
    assert restored.last_login_at == original.last_login_at
    assert restored.created_at == original.created_at


async def test_restored_principal_is_transient(
    configure: Callable[..., FakeRedis],
) -> None:
    """It must be safe to hand to a route without any risk of being flushed."""
    from sqlalchemy import inspect as sa_inspect

    configure()
    settings = get_settings()
    await session_cache.store_principal(_DIGEST, _user(), _far_future(), settings)
    restored = await session_cache.get_principal(_DIGEST, settings)

    assert restored is not None
    state = sa_inspect(restored)
    assert state.session is None
    assert state.transient is True


async def test_viewer_role_survives_the_roundtrip(
    configure: Callable[..., FakeRedis],
) -> None:
    """A role that came back wrong would be a privilege bug, not a cache miss."""
    configure()
    settings = get_settings()
    await session_cache.store_principal(
        _DIGEST, _user(UserRole.viewer), _far_future(), settings
    )
    restored = await session_cache.get_principal(_DIGEST, settings)
    assert restored is not None
    assert restored.role is UserRole.viewer


async def test_the_cookie_value_is_never_part_of_the_key(
    configure: Callable[..., FakeRedis],
) -> None:
    """Keys carry the SHA-256 digest, exactly like `sessions.id`."""
    client = configure()
    settings = get_settings()
    await session_cache.store_principal(_DIGEST, _user(), _far_future(), settings)
    assert list(client.store) == [f"netforge:sess:v1:{_DIGEST}"]


# --- Refusals -------------------------------------------------------------- #


async def test_nothing_is_cached_inside_the_renewal_window(
    configure: Callable[..., FakeRedis],
) -> None:
    """A hit skips `touch_session`, so caching here would stall sliding renewal."""
    client = configure()
    settings = get_settings()
    nearly_expired = datetime.now(UTC) + timedelta(minutes=30)

    await session_cache.store_principal(_DIGEST, _user(), nearly_expired, settings)
    assert client.store == {}


async def test_ttl_is_clamped_to_the_remaining_session_life(
    configure: Callable[..., FakeRedis],
) -> None:
    """An entry must never outlive the session it describes."""
    client = configure(CACHE_SESSION_TTL_SECONDS="3600")
    settings = get_settings()
    # Just past the renewal threshold, so it is cacheable but has less life
    # left than the configured TTL.
    expires = datetime.now(UTC) + timedelta(hours=1, minutes=10)

    await session_cache.store_principal(_DIGEST, _user(), expires, settings)
    ttl = client.expiries[f"netforge:sess:v1:{_DIGEST}"]
    assert 0 < ttl <= 70 * 60


async def test_configured_ttl_wins_when_the_session_outlives_it(
    configure: Callable[..., FakeRedis],
) -> None:
    client = configure(CACHE_SESSION_TTL_SECONDS="30")
    settings = get_settings()
    await session_cache.store_principal(_DIGEST, _user(), _far_future(), settings)
    assert client.expiries[f"netforge:sess:v1:{_DIGEST}"] == 30


async def test_an_expired_entry_is_treated_as_a_miss(
    configure: Callable[..., FakeRedis],
) -> None:
    """Belt and braces: the TTL should have retired it, but if Redis hands one
    back we must not honour an expired session."""
    import json

    client = configure()
    settings = get_settings()
    await session_cache.store_principal(_DIGEST, _user(), _far_future(), settings)

    key = f"netforge:sess:v1:{_DIGEST}"
    payload = json.loads(client.store[key])
    payload["session_expires_at"] = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    client.store[key] = json.dumps(payload).encode("utf-8")

    assert await session_cache.get_principal(_DIGEST, settings) is None


async def test_a_malformed_entry_is_treated_as_a_miss(
    configure: Callable[..., FakeRedis],
) -> None:
    client = configure()
    settings = get_settings()
    client.store[f"netforge:sess:v1:{_DIGEST}"] = (
        b'{"session_expires_at": "2099-01-01T00:00:00+00:00", "id": 1}'
    )
    assert await session_cache.get_principal(_DIGEST, settings) is None


async def test_an_unknown_role_is_treated_as_a_miss(
    configure: Callable[..., FakeRedis],
) -> None:
    """A role we cannot map must fail closed to a DB lookup, not to a default."""
    client = configure()
    settings = get_settings()
    await session_cache.store_principal(_DIGEST, _user(), _far_future(), settings)
    key = f"netforge:sess:v1:{_DIGEST}"
    client.store[key] = client.store[key].replace(b'"admin"', b'"superuser"')
    assert await session_cache.get_principal(_DIGEST, settings) is None


async def test_a_non_dict_payload_is_treated_as_a_miss(
    configure: Callable[..., FakeRedis],
) -> None:
    client = configure()
    settings = get_settings()
    client.store[f"netforge:sess:v1:{_DIGEST}"] = b'"not an object"'
    assert await session_cache.get_principal(_DIGEST, settings) is None


async def test_invalidate_drops_the_entry(configure: Callable[..., FakeRedis]) -> None:
    client = configure()
    settings = get_settings()
    await session_cache.store_principal(_DIGEST, _user(), _far_future(), settings)
    await session_cache.invalidate(_DIGEST)
    assert client.store == {}
    assert await session_cache.get_principal(_DIGEST, settings) is None


async def test_disabled_flag_short_circuits_both_directions(
    configure: Callable[..., FakeRedis],
) -> None:
    client = configure(CACHE_SESSIONS_ENABLED="false")
    settings = get_settings()
    await session_cache.store_principal(_DIGEST, _user(), _far_future(), settings)
    assert client.calls == []
    assert await session_cache.get_principal(_DIGEST, settings) is None
    assert client.calls == []


async def test_everything_is_a_miss_without_redis() -> None:
    settings = get_settings()
    assert await session_cache.get_principal(_DIGEST, settings) is None
    # Must not raise.
    await session_cache.store_principal(_DIGEST, _user(), _far_future(), settings)
    await session_cache.invalidate(_DIGEST)
