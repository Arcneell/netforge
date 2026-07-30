"""The session cache as seen through the real FastAPI stack.

`tests/test_session_cache.py` pins the store's own contract. What matters here
is the wiring: that `get_current_user` actually consults Redis before Postgres,
that a hit skips the two SELECTs, that logout evicts, and that a Bearer token
never lands in the cache.

DB and provider are mocked, same as `tests/test_auth_endpoints.py`.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app import cache
from app.auth.sessions import hash_session_id
from app.config import get_settings
from app.db import get_session as get_db_session
from app.main import app
from app.models.user import Session, User, UserRole

from .test_cache import FakeRedis

_COOKIE = "cookie-value-abc"


def _make_user() -> User:
    return User(
        id=1,
        provider="github",
        subject="42",
        email="alice@example.com",
        display_name="Alice",
        role=UserRole.admin,
    )


def _install_db_mock(session: Session | None, user: User | None) -> AsyncMock:
    session_result = MagicMock()
    session_result.scalar_one_or_none = MagicMock(return_value=session)

    db = AsyncMock()
    db.execute = AsyncMock(return_value=session_result)
    db.get = AsyncMock(return_value=user)
    db.commit = AsyncMock()

    async def _override():
        yield db

    app.dependency_overrides[get_db_session] = _override
    return db


@pytest.fixture
def configure() -> Iterator[Callable[..., FakeRedis]]:
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

    app.dependency_overrides.clear()
    for name in (
        "REDIS_URL",
        "CACHE_KEY_PREFIX",
        "CACHE_SESSIONS_ENABLED",
        "SESSION_MAX_AGE_SECONDS",
    ):
        os.environ.pop(name, None)
    get_settings.cache_clear()
    cache.reset_client()


def _session(expires_in: timedelta = timedelta(hours=4)) -> Session:
    return Session(
        id=hash_session_id(_COOKIE),
        user_id=1,
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + expires_in,
    )


async def _me(cookie: str | None = _COOKIE, **headers: str) -> tuple[int, dict]:
    transport = ASGITransport(app=app)
    cookies = {"netforge_session": cookie} if cookie else None
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/auth/me", cookies=cookies, headers=headers)
    return response.status_code, (response.json() if response.content else {})


async def test_the_first_request_populates_the_cache(
    configure: Callable[..., FakeRedis],
) -> None:
    client = configure()
    _install_db_mock(session=_session(), user=_make_user())

    status, body = await _me()

    assert status == 200
    assert body["email"] == "alice@example.com"
    assert list(client.store) == [f"netforge:sess:v1:{hash_session_id(_COOKIE)}"]


async def test_a_cached_request_skips_both_selects(
    configure: Callable[..., FakeRedis],
) -> None:
    """The point of the cache: no `sessions` lookup, no `users` load."""
    configure()
    db = _install_db_mock(session=_session(), user=_make_user())

    await _me()
    db.execute.reset_mock()
    db.get.reset_mock()

    status, body = await _me()

    assert status == 200
    assert body["role"] == "admin"
    assert db.execute.await_count == 0
    assert db.get.await_count == 0


async def test_logout_evicts_so_the_next_request_is_anonymous(
    configure: Callable[..., FakeRedis],
) -> None:
    """Instant revocation is why sessions live in a table rather than a JWT —
    caching the lookup must not weaken the documented logout path."""
    client = configure()
    _install_db_mock(session=_session(), user=_make_user())
    await _me()
    assert client.store != {}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        logout = await http.post(
            "/api/auth/logout", cookies={"netforge_session": _COOKIE}
        )
    assert logout.status_code == 200
    assert client.store == {}

    # The row is gone too, so the fall-through to Postgres now yields nothing.
    _install_db_mock(session=None, user=None)
    status, _ = await _me()
    assert status == 401


async def test_a_bearer_request_is_never_cached(
    configure: Callable[..., FakeRedis],
) -> None:
    """Token auth writes `last_used_at` and must revoke instantly, so it stays
    on the Postgres path."""
    client = configure()
    _install_db_mock(session=None, user=None)

    status, _ = await _me(cookie=None, authorization="Bearer nfp_whatever")

    assert status == 401
    assert client.store == {}


async def test_disabling_the_session_cache_keeps_the_db_path(
    configure: Callable[..., FakeRedis],
) -> None:
    client = configure(CACHE_SESSIONS_ENABLED="false")
    db = _install_db_mock(session=_session(), user=_make_user())

    await _me()
    await _me()

    assert client.store == {}
    assert db.get.await_count == 2


async def test_a_near_expiry_session_is_renewed_then_cached_at_its_new_expiry(
    configure: Callable[..., FakeRedis],
) -> None:
    """Order matters: renew first, cache second.

    Caching before `touch_session` would store the expiry the renewal just
    replaced, and `_is_cacheable` would then refuse the entry for the rest of
    the session's life.
    """
    client = configure()
    session = _session(timedelta(minutes=20))
    original_expiry = session.expires_at
    db = _install_db_mock(session=session, user=_make_user())

    status, _ = await _me()

    assert status == 200
    assert session.expires_at > original_expiry, "sliding renewal must have fired"
    assert db.commit.await_count >= 1
    assert client.store != {}, "the renewed expiry is far enough out to cache"


async def test_nothing_is_cached_when_sessions_are_shorter_than_the_renewal_window(
    configure: Callable[..., FakeRedis],
) -> None:
    """`SESSION_MAX_AGE_SECONDS` under `_RENEW_THRESHOLD` means every request is
    inside the renewal window, so `touch_session` has to run every time — and a
    cache hit would skip it. `_is_cacheable` is what keeps that safe.
    """
    client = configure(SESSION_MAX_AGE_SECONDS="1800")
    session = _session(timedelta(minutes=20))
    db = _install_db_mock(session=session, user=_make_user())

    await _me()
    await _me()

    assert client.store == {}
    assert db.commit.await_count == 2, "renewal must keep firing on every request"
