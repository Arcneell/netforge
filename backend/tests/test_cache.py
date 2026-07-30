"""Tests for the optional Redis layer (`app/cache.py`).

The contract that matters here is the degradation policy: with no `REDIS_URL`
every helper is a no-op, and when Redis misbehaves the helpers report a miss
instead of raising. A cache that turns an outage into a 500 would make the
stack less available than it was without Redis.

The Lua counter script is exercised separately — wiring in
`tests/test_rate_limit_redis.py`, real semantics against a live Redis in
`tests/integration/test_rate_limit_shared_redis.py`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest

from app import cache
from app.config import get_settings


class FakeRedis:
    """Minimal async stand-in: the four commands `app/cache.py` issues."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.store: dict[str, bytes] = {}
        self.expiries: dict[str, int] = {}
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def _record(self, op: str, *args: object) -> None:
        self.calls.append((op, args))
        if self.fail:
            raise ConnectionError("redis is down")

    async def get(self, key: str) -> bytes | None:
        self._record("get", key)
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._record("set", key, ex)
        self.store[key] = value.encode("utf-8")
        if ex is not None:
            self.expiries[key] = ex

    async def delete(self, *keys: str) -> None:
        self._record("delete", *keys)
        for key in keys:
            self.store.pop(key, None)

    async def ping(self) -> bool:
        self._record("ping")
        return True


@pytest.fixture
def configure() -> Iterator[Callable[..., FakeRedis]]:
    """Wire a `FakeRedis` in as the module client and set `REDIS_URL`.

    `REDIS_URL` has to be set even though the client is injected: several
    helpers gate on `cache_configured()`, which reads settings rather than the
    client. Teardown drops both so no test leaks a client into the next.
    """
    created: list[FakeRedis] = []

    def _apply(*, fail: bool = False, prefix: str = "netforge") -> FakeRedis:
        client = FakeRedis(fail=fail)
        created.append(client)
        _set_env(REDIS_URL="redis://localhost:6379/0", CACHE_KEY_PREFIX=prefix)
        cache._client = client
        cache._client_built = True
        return client

    yield _apply

    cache.reset_client()
    _clear_env()


def _set_env(**values: str) -> None:
    import os

    for name, value in values.items():
        os.environ[name] = value
    get_settings.cache_clear()


def _clear_env() -> None:
    import os

    for name in ("REDIS_URL", "CACHE_KEY_PREFIX"):
        os.environ.pop(name, None)
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _isolate_client() -> Iterator[None]:
    """Every test starts with no client and a closed (re-armed) breaker."""
    cache.reset_client()
    yield
    cache.reset_client()
    _clear_env()


# --- No REDIS_URL: everything is inert ------------------------------------- #


async def test_helpers_are_inert_without_redis_url() -> None:
    assert cache.cache_configured() is False
    assert cache.cache_available() is False
    assert cache.get_client() is None
    assert await cache.get_json("anything") is None
    assert await cache.ping() is False
    # Must not raise, must not need a client.
    await cache.set_json("k", {"a": 1}, ttl_seconds=60)
    await cache.delete("k")


async def test_close_client_without_a_client_is_a_noop() -> None:
    await cache.close_client()


# --- Happy path ------------------------------------------------------------ #


async def test_get_set_roundtrip(configure: Callable[..., FakeRedis]) -> None:
    configure()
    await cache.set_json("thing", {"a": [1, 2], "b": None}, ttl_seconds=42)
    assert await cache.get_json("thing") == {"a": [1, 2], "b": None}


async def test_keys_are_namespaced_by_prefix(configure: Callable[..., FakeRedis]) -> None:
    client = configure(prefix="staging")
    await cache.set_json("thing", 1, ttl_seconds=10)
    assert cache.namespaced("thing") == "staging:thing"
    assert list(client.store) == ["staging:thing"]


async def test_two_prefixes_do_not_share_entries(
    configure: Callable[..., FakeRedis],
) -> None:
    """The reason CACHE_KEY_PREFIX exists: one Redis, two deployments."""
    client = configure(prefix="prod")
    await cache.set_json("thing", "prod-value", ttl_seconds=10)
    _set_env(REDIS_URL="redis://localhost:6379/0", CACHE_KEY_PREFIX="staging")
    assert await cache.get_json("thing") is None
    assert client.store == {"prod:thing": b'"prod-value"'}


async def test_set_json_passes_the_ttl_through(
    configure: Callable[..., FakeRedis],
) -> None:
    client = configure()
    await cache.set_json("thing", 1, ttl_seconds=77)
    assert client.expiries["netforge:thing"] == 77


async def test_delete_namespaces_every_key(configure: Callable[..., FakeRedis]) -> None:
    client = configure()
    await cache.set_json("a", 1, ttl_seconds=10)
    await cache.set_json("b", 2, ttl_seconds=10)
    await cache.delete("a", "b")
    assert client.store == {}
    assert ("delete", ("netforge:a", "netforge:b")) in client.calls


async def test_ping_reports_reachability(configure: Callable[..., FakeRedis]) -> None:
    configure()
    assert await cache.ping() is True


async def test_ping_reports_down_when_redis_raises(
    configure: Callable[..., FakeRedis],
) -> None:
    configure(fail=True)
    assert await cache.ping() is False


# --- Refusals that must not raise ----------------------------------------- #


async def test_non_positive_ttl_writes_nothing(
    configure: Callable[..., FakeRedis],
) -> None:
    """An entry with no expiry is a leak, so a caller with no TTL gets no write."""
    client = configure()
    await cache.set_json("thing", 1, ttl_seconds=0)
    await cache.set_json("thing", 1, ttl_seconds=-5)
    assert client.calls == []


async def test_unserialisable_value_is_dropped_not_raised(
    configure: Callable[..., FakeRedis],
) -> None:
    client = configure()

    class Opaque:
        __slots__ = ()

    # `default=str` in `set_json` handles most objects; a dict *key* that isn't
    # a string is what json.dumps genuinely refuses.
    await cache.set_json("thing", {Opaque(): 1}, ttl_seconds=10)
    assert client.calls == []


async def test_undecodable_stored_value_is_a_miss(
    configure: Callable[..., FakeRedis],
) -> None:
    client = configure()
    client.store["netforge:thing"] = b"this is not json"
    assert await cache.get_json("thing") is None


async def test_delete_with_no_keys_touches_nothing(
    configure: Callable[..., FakeRedis],
) -> None:
    client = configure()
    await cache.delete()
    assert client.calls == []


# --- Breaker -------------------------------------------------------------- #


async def test_failure_trips_the_breaker_and_stops_calling_redis(
    configure: Callable[..., FakeRedis],
) -> None:
    """One failure is enough: a cache command is sub-millisecond, so a failure
    means the server is unreachable, not that we were unlucky."""
    client = configure(fail=True)

    assert await cache.get_json("thing") is None
    assert len(client.calls) == 1
    assert cache.cache_available() is False

    # Parked — no further commands are attempted.
    assert await cache.get_json("thing") is None
    await cache.set_json("thing", 1, ttl_seconds=10)
    await cache.delete("thing")
    assert len(client.calls) == 1


async def test_ping_bypasses_the_breaker(configure: Callable[..., FakeRedis]) -> None:
    """`/api/health` must report what Redis is doing now, not what it was doing
    when the breaker tripped."""
    client = configure(fail=True)
    await cache.get_json("thing")  # trips it
    client.fail = False
    assert await cache.ping() is True


async def test_breaker_rearms_after_cooldown(
    configure: Callable[..., FakeRedis], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cache, "_breaker", cache.CircuitBreaker(0.0))
    client = configure(fail=True)
    await cache.get_json("thing")
    client.fail = False
    assert await cache.get_json("thing") is None  # miss, but it did ask
    assert len(client.calls) == 2


# --- Client construction --------------------------------------------------- #


def test_get_client_is_built_once_and_reused() -> None:
    _set_env(REDIS_URL="redis://localhost:6379/0")
    first = cache.get_client()
    assert first is not None
    assert cache.get_client() is first


def test_get_client_honours_the_configured_timeout() -> None:
    _set_env(REDIS_URL="redis://localhost:6379/0", REDIS_TIMEOUT_SECONDS="1.25")
    client = cache.get_client()
    assert client is not None
    kwargs = client.connection_pool.connection_kwargs
    assert kwargs["socket_timeout"] == 1.25
    assert kwargs["socket_connect_timeout"] == 1.25
    import os

    os.environ.pop("REDIS_TIMEOUT_SECONDS", None)
    get_settings.cache_clear()


def test_blank_redis_url_counts_as_unset() -> None:
    _set_env(REDIS_URL="   ")
    assert cache.cache_configured() is False
    assert cache.get_client() is None
