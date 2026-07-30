"""Optional Redis layer — client, key namespacing, and a JSON value cache.

Redis is **opt-in and never a hard dependency of a deployment**. With
`REDIS_URL` empty (the default) every helper in this module reports "no
cache" and each consumer keeps exactly the behaviour it had before this
module existed:

  - `auth/dependencies.py` resolves the session against Postgres every time.
  - `services/read_cache.py` calls its builder on every request.
  - `middleware/rate_limit.py` / `services/ai/rate_limit.py` keep counting in
    `rate_limit_counters` (or in-process, per `RATE_LIMIT_STORE`).

Same posture as `AI_ENABLED=false` and `RATE_LIMIT_STORE=memory`: a
self-hoster who does not want a fourth container gets a working stack, and
nothing here can turn into a hard failure for them.

Degradation policy: NEVER RAISE, NEVER BLOCK
--------------------------------------------
`get_json` / `set_json` / `delete` swallow every exception and report a
miss. A cache that is down must look exactly like a cache that is cold —
turning a Redis hiccup into a 500 would make the stack *less* available than
it was without Redis, which is the opposite of the point.

A `CircuitBreaker` (shared with the rate-limit store) keeps an outage from
costing every request a connect timeout: one failure parks the cache for
`_CIRCUIT_COOLDOWN_SECONDS` and every helper short-circuits to "no cache"
until the cooldown elapses.

The rate limiters do **not** go through these helpers. They hold the raw
client and let `rate_limit_store.try_consume_redis` raise, because the two
limiters make deliberately opposite calls about what a counter outage
means (fail open for load, fail closed for spend — see their docstrings).

Socket timeouts
---------------
`redis_timeout_seconds` caps both connect and command time. It is
deliberately sub-second: every call here sits on a request's critical path
and the fallback (ask Postgres / rebuild) is always available, so waiting
on a wedged Redis is never the better trade. `retry_on_timeout` is off for
the same reason — a retry doubles the latency we are trying to avoid.

Key namespacing
---------------
Every key is prefixed with `CACHE_KEY_PREFIX` (default `netforge`) so one
Redis instance can host several NetForge deployments — or NetForge next to
something else — without collisions. Value keys additionally carry the app
version (see `services/read_cache.py`), so a release that changes a
response schema cannot serve a payload serialised by the previous one.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from app.config import get_settings
from app.services.rate_limit_store import CircuitBreaker

if TYPE_CHECKING:  # pragma: no cover - typing only
    from redis.asyncio import Redis

logger = logging.getLogger("netforge.cache")

# How long the cache stays parked after a failure. Matches the rate
# limiter's cooldown (`middleware/rate_limit.py`): short enough that a blip
# barely costs us hit rate, long enough that a real outage does not re-pay a
# connect timeout on every request.
_CIRCUIT_COOLDOWN_SECONDS = 30.0

_breaker = CircuitBreaker(_CIRCUIT_COOLDOWN_SECONDS)

# Lazy singleton. redis-py's `from_url` only builds a connection pool — no
# socket is opened until the first command — so building this at first use
# costs nothing and cannot fail on an unreachable server.
_client: Redis | None = None
_client_built = False


def cache_configured() -> bool:
    """True when `REDIS_URL` is set. Says nothing about reachability."""
    return bool(get_settings().redis_url.strip())


def get_client() -> Redis | None:
    """The shared async Redis client, or None when Redis is not configured.

    Not breaker-guarded: building the pool never talks to the server, and
    the rate limiters need a handle even while the *cache* breaker is open
    (their own breakers decide what a counter failure means). Command-level
    protection lives in the `get_json` / `set_json` / `delete` helpers.
    """
    global _client, _client_built
    if _client_built:
        return _client
    _client_built = True
    settings = get_settings()
    url = settings.redis_url.strip()
    if not url:
        _client = None
        return None
    try:
        from redis.asyncio import Redis as AsyncRedis
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise RuntimeError(
            "REDIS_URL is set but the `redis` package is not installed. "
            "Reinstall the backend dependencies (pip install -e '.[dev]') "
            "or unset REDIS_URL to run without a cache."
        ) from exc
    timeout = settings.redis_timeout_seconds
    _client = AsyncRedis.from_url(
        url,
        # Values are JSON encoded by this module, so bytes in / bytes out.
        # Decoding to str here would only add a pass we do not need.
        decode_responses=False,
        socket_connect_timeout=timeout,
        socket_timeout=timeout,
        retry_on_timeout=False,
        # Lets the pool notice a connection that died while idle (a Redis
        # restart, an idle-timeout proxy) and reconnect, instead of handing
        # the next caller a dead socket.
        health_check_interval=30,
    )
    logger.info("cache.enabled prefix=%s timeout_s=%s", settings.cache_key_prefix, timeout)
    return _client


async def close_client() -> None:
    """Release the connection pool. Called from the app's lifespan shutdown."""
    global _client, _client_built
    client = _client
    _client = None
    _client_built = False
    if client is None:
        return
    try:
        await client.aclose()
    except Exception:  # pragma: no cover - shutdown best effort
        logger.debug("cache.close failed", exc_info=True)


def reset_client() -> None:
    """Test hook — forget the cached client and re-arm the breaker.

    Does not close the pool: tests that need that call `close_client`. This
    exists so a test can flip `REDIS_URL` via monkeypatch and have the next
    `get_client()` honour it.
    """
    global _client, _client_built
    _client = None
    _client_built = False
    _breaker.record_success()


def namespaced(key: str) -> str:
    """Prefix `key` with `CACHE_KEY_PREFIX`."""
    return f"{get_settings().cache_key_prefix}:{key}"


def cache_available() -> bool:
    """True when Redis is configured and not currently parked by the breaker."""
    return get_client() is not None and not _breaker.is_open()


async def get_json(key: str) -> Any | None:
    """Read and JSON-decode `key`. None on miss, on decode failure, or when
    the cache is unavailable — the caller cannot tell those apart and does
    not need to: all three mean "compute it yourself"."""
    client = get_client()
    if client is None or _breaker.is_open():
        return None
    try:
        raw = await client.get(namespaced(key))
    except Exception:
        _record_failure("get", key)
        return None
    _breaker.record_success()
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        # A value we cannot decode is a value written by a different codec
        # or a truncated write. Treat as a miss rather than propagating; the
        # caller will recompute and overwrite it.
        logger.warning("cache.decode_failed key=%s", key)
        return None


async def set_json(key: str, value: Any, *, ttl_seconds: int) -> None:
    """JSON-encode `value` under `key` with an expiry. Best effort.

    `ttl_seconds <= 0` is a no-op: a cache entry with no expiry is a leak,
    and every caller here has a meaningful TTL to give.
    """
    client = get_client()
    if client is None or _breaker.is_open() or ttl_seconds <= 0:
        return
    try:
        payload = json.dumps(value, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        logger.warning("cache.encode_failed key=%s", key)
        return
    try:
        await client.set(namespaced(key), payload, ex=ttl_seconds)
    except Exception:
        _record_failure("set", key)
        return
    _breaker.record_success()


async def delete(*keys: str) -> None:
    """Drop `keys`. Best effort — see the module docstring.

    Used by the session-cache invalidation path (logout, session delete).
    A failure here means a revoked session can stay cached until its TTL
    elapses, which is why `CACHE_SESSION_TTL_SECONDS` is short by default;
    it is logged at warning level so an operator can see it happening.
    """
    client = get_client()
    if client is None or _breaker.is_open() or not keys:
        return
    try:
        await client.delete(*[namespaced(k) for k in keys])
    except Exception:
        _record_failure("delete", ",".join(keys))
        return
    _breaker.record_success()


async def ping() -> bool:
    """True when Redis answers. Used by `/api/health`; ignores the breaker so
    the endpoint reports what Redis is doing *now*, not what it was doing
    when the breaker tripped."""
    client = get_client()
    if client is None:
        return False
    try:
        await client.ping()
    except Exception:
        return False
    return True


def _record_failure(op: str, key: str) -> None:
    _breaker.record_failure()
    logger.warning(
        "cache.degraded op=%s key=%s cooldown_s=%d — serving without a cache",
        op,
        key,
        int(_CIRCUIT_COOLDOWN_SECONDS),
        exc_info=True,
    )


__all__ = [
    "cache_available",
    "cache_configured",
    "close_client",
    "delete",
    "get_client",
    "get_json",
    "namespaced",
    "ping",
    "reset_client",
    "set_json",
]
