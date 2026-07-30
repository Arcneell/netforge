"""Wiring tests for the Redis rate-limit backend.

Scope: that `try_consume_redis` builds the right key, passes the right ARGV,
translates the script's return into a `Decision`, and that both call sites pick
it up when `RATE_LIMIT_STORE=redis`. The Lua itself — atomicity, the server
clock, EXPIRE — needs a real Redis and lives in
`tests/integration/test_rate_limit_shared_redis.py`.

The fake below reimplements the script's *semantics* in Python so the contract
(`a rejected call does not consume budget`) is pinned in the unit suite too.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from app.config import get_settings
from app.services import rate_limit_store as store
from app.services.rate_limit_store import (
    SCOPE_AI_USER,
    SCOPE_WRITE_IP,
    redis_bucket_key,
    try_consume_redis,
)


class FakeScript:
    """Python twin of `_CONSUME_LUA`, sharing its clock with the fake client."""

    def __init__(self, client: FakeRedisCounter) -> None:
        self._client = client

    async def __call__(self, *, keys: list[str], args: list[int]) -> list[int]:
        if self._client.fail:
            raise ConnectionError("redis is down")
        window, limit = int(args[0]), int(args[1])
        now = self._client.now
        bucket = now // window
        remaining = max(1, (bucket + 1) * window - now)
        key = f"{keys[0]}:{bucket}"
        self._client.seen_keys.append(key)
        current = self._client.counters.get(key, 0)
        if current >= limit:
            return [-1, remaining]
        self._client.counters[key] = current + 1
        if current == 0:
            self._client.expiries[key] = remaining
        return [current + 1, remaining]


class FakeRedisCounter:
    def __init__(self, *, now: int = 1_000_000, fail: bool = False) -> None:
        self.now = now
        self.fail = fail
        self.counters: dict[str, int] = {}
        self.expiries: dict[str, int] = {}
        self.seen_keys: list[str] = []
        self.registrations = 0

    def register_script(self, body: str) -> FakeScript:
        self.registrations += 1
        assert "redis.call('TIME')" in body, "the bucket must come from the server clock"
        return FakeScript(self)


@pytest.fixture(autouse=True)
def _reset_script_cache() -> Iterator[None]:
    store.reset_redis_script_cache()
    yield
    store.reset_redis_script_cache()


# --- Decision contract ----------------------------------------------------- #


async def test_hits_increment_until_the_limit() -> None:
    client = FakeRedisCounter()
    seen = []
    for _ in range(3):
        decision = await try_consume_redis(
            client,
            namespace="netforge",
            scope=SCOPE_WRITE_IP,
            key="10.0.0.1",
            limit=3,
            window_seconds=60,
        )
        seen.append((decision.allowed, decision.hits))
    assert seen == [(True, 1), (True, 2), (True, 3)]


async def test_the_call_past_the_limit_is_rejected() -> None:
    client = FakeRedisCounter()
    for _ in range(2):
        await try_consume_redis(
            client,
            namespace="netforge",
            scope=SCOPE_WRITE_IP,
            key="ip",
            limit=2,
            window_seconds=60,
        )
    decision = await try_consume_redis(
        client,
        namespace="netforge",
        scope=SCOPE_WRITE_IP,
        key="ip",
        limit=2,
        window_seconds=60,
    )
    assert decision.allowed is False
    assert decision.hits == 2
    assert decision.retry_after_seconds >= 1


async def test_a_rejected_call_does_not_consume_budget() -> None:
    """Same semantics the Postgres store preserves with `WHERE hits < :limit`:
    hammering while throttled must not extend the penalty."""
    client = FakeRedisCounter()
    await try_consume_redis(
        client, namespace="n", scope=SCOPE_WRITE_IP, key="ip", limit=1, window_seconds=60
    )
    for _ in range(5):
        await try_consume_redis(
            client,
            namespace="n",
            scope=SCOPE_WRITE_IP,
            key="ip",
            limit=1,
            window_seconds=60,
        )
    assert list(client.counters.values()) == [1]


async def test_a_zero_limit_allows_nothing_and_writes_nothing() -> None:
    client = FakeRedisCounter()
    decision = await try_consume_redis(
        client, namespace="n", scope=SCOPE_WRITE_IP, key="ip", limit=0, window_seconds=60
    )
    assert decision.allowed is False
    assert client.counters == {}


async def test_scopes_and_keys_have_separate_budgets() -> None:
    client = FakeRedisCounter()
    for scope in (SCOPE_WRITE_IP, SCOPE_AI_USER):
        for key in ("a", "b"):
            decision = await try_consume_redis(
                client,
                namespace="n",
                scope=scope,
                key=key,
                limit=1,
                window_seconds=60,
            )
            assert decision.allowed is True
    assert len(client.counters) == 4


async def test_the_bucket_rolls_with_the_server_clock() -> None:
    """A tumbling bucket: crossing the boundary yields a fresh budget."""
    client = FakeRedisCounter(now=59)
    await try_consume_redis(
        client, namespace="n", scope=SCOPE_WRITE_IP, key="ip", limit=1, window_seconds=60
    )
    client.now = 60
    decision = await try_consume_redis(
        client, namespace="n", scope=SCOPE_WRITE_IP, key="ip", limit=1, window_seconds=60
    )
    assert decision.allowed is True
    assert client.seen_keys == ["n:rl:write_ip:ip:0", "n:rl:write_ip:ip:1"]


async def test_expiry_never_outlives_the_bucket() -> None:
    """`EXPIRE` is set to the time left in the current bucket, so a key cannot
    survive into the next one — the whole of this backend's housekeeping."""
    # 1_000_020 is a bucket boundary for a 60s window (1_000_020 / 60 = 16_667),
    # so this clock sits 45s in and the key must expire in the remaining 15.
    client = FakeRedisCounter(now=1_000_020 + 45)
    await try_consume_redis(
        client, namespace="n", scope=SCOPE_WRITE_IP, key="ip", limit=5, window_seconds=60
    )
    assert list(client.expiries.values()) == [15]


async def test_namespace_isolates_deployments() -> None:
    client = FakeRedisCounter()
    for namespace in ("prod", "staging"):
        await try_consume_redis(
            client,
            namespace=namespace,
            scope=SCOPE_WRITE_IP,
            key="ip",
            limit=1,
            window_seconds=60,
        )
    assert len(client.counters) == 2


def test_the_bucket_key_shape_is_stable() -> None:
    assert redis_bucket_key("netforge", SCOPE_AI_USER, "42") == "netforge:rl:ai_user:42"


async def test_the_script_is_registered_once_per_client() -> None:
    """EVALSHA, not a ~700-byte EVAL on every limited request."""
    client = FakeRedisCounter()
    for _ in range(3):
        await try_consume_redis(
            client,
            namespace="n",
            scope=SCOPE_WRITE_IP,
            key="ip",
            limit=10,
            window_seconds=60,
        )
    assert client.registrations == 1


async def test_a_new_client_gets_its_own_registration() -> None:
    first, second = FakeRedisCounter(), FakeRedisCounter()
    for client in (first, second):
        await try_consume_redis(
            client,
            namespace="n",
            scope=SCOPE_WRITE_IP,
            key="ip",
            limit=10,
            window_seconds=60,
        )
    assert (first.registrations, second.registrations) == (1, 1)


async def test_failures_propagate_to_the_caller() -> None:
    """The two limiters make opposite calls about what an outage means, so this
    function must not decide for them."""
    client = FakeRedisCounter(fail=True)
    with pytest.raises(ConnectionError):
        await try_consume_redis(
            client,
            namespace="n",
            scope=SCOPE_WRITE_IP,
            key="ip",
            limit=1,
            window_seconds=60,
        )


# --- Call sites ------------------------------------------------------------ #


@pytest.fixture
def redis_store_env() -> Iterator[None]:
    os.environ["RATE_LIMIT_STORE"] = "redis"
    os.environ["REDIS_URL"] = "redis://localhost:6379/0"
    get_settings.cache_clear()
    yield
    os.environ["RATE_LIMIT_STORE"] = "memory"
    os.environ.pop("REDIS_URL", None)
    get_settings.cache_clear()


async def test_the_write_limiter_uses_redis_when_given_a_client() -> None:
    from app.middleware.rate_limit import WriteRateLimitMiddleware

    client = FakeRedisCounter()

    async def _app(scope: dict, receive: object, send: object) -> None:
        pass

    middleware = WriteRateLimitMiddleware(
        _app,
        max_per_window=1,
        window_seconds=60,
        redis_client=client,
        cache_key_prefix="netforge",
    )
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/sites",
        "headers": [],
        "client": ("10.0.0.9", 0),
    }
    statuses: list[int] = []

    async def _send(message: dict) -> None:
        if message["type"] == "http.response.start":
            statuses.append(message["status"])

    async def _receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    await middleware(scope, _receive, _send)
    await middleware(scope, _receive, _send)

    assert statuses == [429], "the second write must be throttled by the Redis counter"
    assert client.seen_keys[0].startswith("netforge:rl:write_ip:10.0.0.9:")


async def test_the_write_limiter_does_not_purge_on_the_redis_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`maybe_purge_expired` is a Postgres-only chore; Redis uses EXPIRE."""
    from app.middleware import rate_limit as middleware_module

    purges: list[int] = []

    async def _spy(_engine: object) -> None:
        purges.append(1)

    monkeypatch.setattr(middleware_module, "maybe_purge_expired", _spy)

    async def _app(scope: dict, receive: object, send: object) -> None:
        pass

    middleware = middleware_module.WriteRateLimitMiddleware(
        _app,
        max_per_window=10,
        window_seconds=60,
        redis_client=FakeRedisCounter(),
    )
    await middleware(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/sites",
            "headers": [],
            "client": ("10.0.0.1", 0),
        },
        lambda: None,
        _noop_send,
    )
    assert purges == []


async def _noop_send(_message: dict) -> None:
    return None


async def test_the_ai_limiter_uses_redis_and_still_fails_closed(
    redis_store_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.ai.rate_limit import AIRateLimitExceeded, consume_ai_quota

    client = FakeRedisCounter()
    monkeypatch.setattr("app.cache.get_client", lambda: client)

    monkeypatch.setenv("AI_RATE_LIMIT_CALLS", "1")
    get_settings.cache_clear()

    await consume_ai_quota(5)
    with pytest.raises(AIRateLimitExceeded):
        await consume_ai_quota(5)
    assert client.seen_keys[0].startswith("netforge:rl:ai_user:5:")

    # An unreachable counter must 429 rather than let spend through.
    client.fail = True
    with pytest.raises(AIRateLimitExceeded):
        await consume_ai_quota(6)


async def test_the_ai_limiter_fails_closed_when_redis_is_not_configured(
    redis_store_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.ai.rate_limit import AIRateLimitExceeded, consume_ai_quota

    monkeypatch.setattr("app.cache.get_client", lambda: None)
    with pytest.raises(AIRateLimitExceeded):
        await consume_ai_quota(5)
