"""Rate-limit counters and the cache helpers against a real Redis.

What the unit suite structurally cannot cover:

- That `_CONSUME_LUA` is valid Lua and that redis-py's `register_script` /
  EVALSHA path actually runs it. A fake `register_script` proves nothing about
  the script body.
- That the check-and-increment really is atomic: 40 simultaneous hits must
  produce the numbers 1 to 40 exactly once each, with nothing lost to a
  read-modify-write race. This is the whole reason the logic is a script
  rather than a GET followed by an INCR.
- That two *actually distinct* clients — the stand-in for two uvicorn workers
  or two replicas — share one budget and agree on the bucket, because the
  boundary comes from the Redis server clock (`TIME`) and not from each
  process's own.
- That `EXPIRE` is really set, so buckets retire themselves and Redis needs no
  equivalent of `purge_expired`.
- That `app/cache.py` speaks to a real server correctly (round trip, TTL,
  namespacing).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.services.rate_limit_store import (
    SCOPE_AI_USER,
    SCOPE_WRITE_IP,
    redis_bucket_key,
    reset_redis_script_cache,
    try_consume_redis,
)

from .conftest import INTEGRATION_REDIS_URL_VAR, integration_redis_url

if not integration_redis_url():
    pytest.skip(
        f"{INTEGRATION_REDIS_URL_VAR} is not set — skipping Redis integration tests",
        allow_module_level=True,
    )

_NAMESPACE = "it"
# Long enough that no test in this module can straddle a bucket boundary and
# see a "fresh" budget mid-assertion.
_WINDOW = 300


@pytest.fixture(autouse=True)
def _reset_script_cache() -> AsyncIterator[None]:
    """The script is cached against the client it was registered on, and this
    suite builds a new client per test."""
    reset_redis_script_cache()
    yield
    reset_redis_script_cache()


@pytest.fixture
async def workers(redis_client: Any) -> AsyncIterator[tuple[Any, Any]]:
    """Two independent clients on the same Redis, plus a flushed database.

    Separate connection pools, separate sockets: as close to two processes as a
    single test can get without forking. `redis_client` is requested only for
    its `flushdb`, so the two below start clean.
    """
    from redis.asyncio import Redis

    url = integration_redis_url()
    assert url is not None
    a = Redis.from_url(url, decode_responses=False)
    b = Redis.from_url(url, decode_responses=False)
    try:
        yield a, b
    finally:
        await a.aclose()
        await b.aclose()


async def _consume(client: Any, key: str, limit: int) -> Any:
    return await try_consume_redis(
        client,
        namespace=_NAMESPACE,
        scope=SCOPE_WRITE_IP,
        key=key,
        limit=limit,
        window_seconds=_WINDOW,
    )


# --- The script actually runs ---------------------------------------------- #


async def test_the_script_runs_and_counts(redis_client: Any) -> None:
    seen = [(await _consume(redis_client, "10.0.0.1", 3)).hits for _ in range(3)]
    assert seen == [1, 2, 3]


async def test_the_call_past_the_limit_is_rejected(redis_client: Any) -> None:
    for _ in range(3):
        assert (await _consume(redis_client, "ip", 3)).allowed is True
    decision = await _consume(redis_client, "ip", 3)
    assert decision.allowed is False
    assert decision.hits == 3
    assert 1 <= decision.retry_after_seconds <= _WINDOW


async def test_a_rejected_call_does_not_consume_budget(redis_client: Any) -> None:
    """Hammering while throttled must not extend the penalty — the semantics the
    Postgres store gets from `WHERE hits < :limit` on its DO UPDATE."""
    await _consume(redis_client, "ip", 1)
    for _ in range(10):
        await _consume(redis_client, "ip", 1)

    stored = await redis_client.keys(f"{_NAMESPACE}:rl:*")
    assert len(stored) == 1
    assert int(await redis_client.get(stored[0])) == 1


# --- The headline guarantees ---------------------------------------------- #


async def test_two_workers_share_one_budget(workers: tuple[Any, Any]) -> None:
    """The reason the counter is not a per-process deque: before that, N workers
    enforced N x the configured cap."""
    a, b = workers
    limit = 4

    assert (await _consume(a, "shared", limit)).hits == 1
    assert (await _consume(b, "shared", limit)).hits == 2
    assert (await _consume(a, "shared", limit)).hits == 3
    assert (await _consume(b, "shared", limit)).hits == 4

    # Fifth call from either side is over the shared cap.
    assert (await _consume(a, "shared", limit)).allowed is False
    assert (await _consume(b, "shared", limit)).allowed is False


async def test_two_workers_agree_on_the_bucket(workers: tuple[Any, Any]) -> None:
    """The boundary comes from the Redis server clock, so a little NTP skew
    between replicas cannot land them on different buckets."""
    a, b = workers
    await _consume(a, "clock", 10)
    await _consume(b, "clock", 10)

    keys = await a.keys(f"{redis_bucket_key(_NAMESPACE, SCOPE_WRITE_IP, 'clock')}:*")
    assert len(keys) == 1, "both workers must have incremented the same bucket key"


async def test_concurrent_hits_lose_nothing(redis_client: Any) -> None:
    """40 simultaneous consumes must yield 1..40 exactly once each. A GET
    followed by an INCR from Python would drop counts here."""
    limit = 40
    decisions = await asyncio.gather(
        *(_consume(redis_client, "concurrent", limit) for _ in range(limit))
    )
    assert sorted(d.hits for d in decisions) == list(range(1, limit + 1))
    assert all(d.allowed for d in decisions)


async def test_concurrent_hits_past_the_cap_are_all_rejected(
    redis_client: Any,
) -> None:
    limit = 10
    decisions = await asyncio.gather(
        *(_consume(redis_client, "burst", limit) for _ in range(limit + 15))
    )
    allowed = [d for d in decisions if d.allowed]
    assert len(allowed) == limit
    assert sorted(d.hits for d in allowed) == list(range(1, limit + 1))


async def test_buckets_expire_themselves(redis_client: Any) -> None:
    """No `purge_expired` equivalent is needed: this is the housekeeping."""
    await _consume(redis_client, "ttl", 5)
    keys = await redis_client.keys(f"{_NAMESPACE}:rl:*")
    assert len(keys) == 1
    ttl = await redis_client.ttl(keys[0])
    assert 0 < ttl <= _WINDOW


async def test_scopes_do_not_share_a_budget(redis_client: Any) -> None:
    """An export binge must not eat a user's AI quota, and vice versa."""
    for scope in (SCOPE_WRITE_IP, SCOPE_AI_USER):
        decision = await try_consume_redis(
            redis_client,
            namespace=_NAMESPACE,
            scope=scope,
            key="1",
            limit=1,
            window_seconds=_WINDOW,
        )
        assert decision.allowed is True
    assert len(await redis_client.keys(f"{_NAMESPACE}:rl:*")) == 2


async def test_a_short_window_rolls_to_a_fresh_budget(redis_client: Any) -> None:
    """Tumbling buckets: crossing the boundary hands back the full budget. Uses a
    1s window so the test can actually wait for it."""
    assert (
        await try_consume_redis(
            redis_client,
            namespace=_NAMESPACE,
            scope=SCOPE_WRITE_IP,
            key="rolling",
            limit=1,
            window_seconds=1,
        )
    ).allowed is True

    await asyncio.sleep(1.2)

    assert (
        await try_consume_redis(
            redis_client,
            namespace=_NAMESPACE,
            scope=SCOPE_WRITE_IP,
            key="rolling",
            limit=1,
            window_seconds=1,
        )
    ).allowed is True


# --- app/cache.py against a real server ----------------------------------- #


@pytest.fixture
def cache_configured(redis_client: Any) -> AsyncIterator[None]:
    """Point `app/cache.py` at the integration Redis for one test."""
    import os

    from app import cache
    from app.config import get_settings

    url = integration_redis_url()
    assert url is not None
    os.environ["REDIS_URL"] = url
    os.environ["CACHE_KEY_PREFIX"] = "it-cache"
    get_settings.cache_clear()
    cache.reset_client()
    yield
    os.environ.pop("REDIS_URL", None)
    os.environ.pop("CACHE_KEY_PREFIX", None)
    get_settings.cache_clear()
    cache.reset_client()


async def test_cache_roundtrip_against_a_real_server(
    cache_configured: None, redis_client: Any
) -> None:
    from app import cache

    assert await cache.ping() is True
    await cache.set_json("thing", {"a": [1, 2, 3]}, ttl_seconds=60)
    assert await cache.get_json("thing") == {"a": [1, 2, 3]}

    assert await redis_client.exists("it-cache:thing") == 1
    ttl = await redis_client.ttl("it-cache:thing")
    assert 0 < ttl <= 60

    await cache.delete("thing")
    assert await cache.get_json("thing") is None
    await cache.close_client()
