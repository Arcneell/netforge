"""Per-IP rate limit on write methods, backed by a shared DB counter.

The audit log and DB integrity already protect against accidental damage,
but a hot-looped script or a curl mistake could still flood writes and burn
through DB connections. We cap writes to N per window per IP.

Where the counter lives
-----------------------
In `rate_limit_counters` (PostgreSQL), not in this process. The previous
in-memory `deque` was per worker, so a deployment with N uvicorn workers or
N replicas enforced N x the configured cap and a script could simply spread
its load across workers. See `app/services/rate_limit_store.py` for the
schema/algorithm rationale (tumbling buckets, single atomic UPSERT, why
Postgres rather than Redis).

Cost on the hot path: exactly one extra statement — one round trip on an
AUTOCOMMIT connection — for each POST/PUT/PATCH/DELETE. Reads are never
rate-limited: the dashboard and topology views fire several GETs per page
load and we don't want to penalise normal browsing. Exempt paths (health,
auth) skip the counter entirely, so probes cost nothing.

Degradation policy: FAIL OPEN
-----------------------------
If the counter cannot be read/written, the request is *allowed* through,
after being counted against a process-local fallback window (the legacy
per-worker algorithm). Rationale:

- This limiter guards against abuse, and every request it guards is a
  write that needs the very database that just failed. Failing closed
  would convert a counter hiccup into a total write outage while
  protecting nothing — the writes would fail on their own anyway.
- The fallback still caps a runaway script at `limit` per worker, i.e. it
  degrades to exactly the behaviour this module had before the shared
  counter existed, which was considered acceptable for years.

The AI limiter (`app/services/ai/rate_limit.py`) makes the *opposite*
choice, deliberately: it guards spend, not load.

A circuit breaker keeps a Postgres outage from costing every write a
connection timeout — one failure parks the DB path for
`_CIRCUIT_COOLDOWN_SECONDS`, and the fallback window carries the load.

Implementation note: this is a raw ASGI middleware, NOT a
`BaseHTTPMiddleware` subclass. Starlette's `BaseHTTPMiddleware` bridges
the response through an anyio memory stream, which silently breaks
`text/event-stream` streaming (chunks pile up until the response ends).
The raw ASGI shape pipes `(scope, receive, send)` straight through, so
SSE on `/api/ai/query/stream` actually flushes per-token.
"""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.types import ASGIApp, Receive, Scope, Send

from app.services.rate_limit_store import (
    SCOPE_WRITE_IP,
    CircuitBreaker,
    Decision,
    InProcessWindows,
    maybe_purge_expired,
    try_consume,
)
from app.utils.request import client_ip

logger = logging.getLogger("netforge")

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Paths that should pass through unconditionally. Health probes must not be
# throttled, and the OAuth callback is a one-shot redirect that can briefly
# happen multiple times in legitimate flows (browser back, page reloads).
_EXEMPT_PATHS = frozenset(
    {"/api/health", "/api/auth/login", "/api/auth/callback", "/api/auth/logout"}
)

# How long the DB path stays parked after a failure. 30s is short enough
# that a blip barely widens the cap and long enough that a real outage does
# not re-pay a connection timeout on every write.
_CIRCUIT_COOLDOWN_SECONDS = 30.0


class WriteRateLimitMiddleware:
    """Raw ASGI middleware — see module docstring for why not BaseHTTPMiddleware."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_per_window: int,
        window_seconds: int,
        engine: AsyncEngine | None = None,
    ) -> None:
        """`engine` is the shared-counter backend.

        Passing `None` selects the legacy process-local window. That is the
        `RATE_LIMIT_STORE=memory` mode (single-worker deployments that want
        zero extra DB traffic) and what the unit suite uses so it never
        needs a database.
        """
        self.app = app
        self._max = max_per_window
        self._window = int(window_seconds)
        self._engine = engine
        self._fallback = InProcessWindows()
        self._breaker = CircuitBreaker(_CIRCUIT_COOLDOWN_SECONDS)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        path = scope.get("path", "")
        if method not in WRITE_METHODS or path in _EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        # Build a tiny Request just to reuse the `client_ip` resolution logic
        # (it normalises X-Real-IP vs scope["client"]).
        request = Request(scope)
        key = client_ip(request) or "unknown"
        decision = await self._consume(key)
        if not decision.allowed:
            await self._reject(decision, scope, receive, send)
            return

        await self.app(scope, receive, send)

    async def _consume(self, key: str) -> Decision:
        """Count one write for `key`, falling back in-process on DB trouble."""
        if self._engine is None or self._breaker.is_open():
            return self._fallback.consume(key, limit=self._max, window_seconds=self._window)
        try:
            decision = await try_consume(
                self._engine,
                scope=SCOPE_WRITE_IP,
                key=key,
                limit=self._max,
                window_seconds=self._window,
            )
        except Exception:
            self._breaker.record_failure()
            logger.warning(
                "rate_limit.write.degraded reason=counter_unavailable "
                "cooldown_s=%s — falling back to a per-worker window",
                int(_CIRCUIT_COOLDOWN_SECONDS),
                exc_info=True,
            )
            return self._fallback.consume(key, limit=self._max, window_seconds=self._window)
        self._breaker.record_success()
        # Housekeeping, throttled to once per 10 minutes per worker and
        # never allowed to raise. Hung off the write path because it is the
        # only path that creates counter rows in the first place.
        await maybe_purge_expired(self._engine)
        return decision

    async def _reject(
        self, decision: Decision, scope: Scope, receive: Receive, send: Send
    ) -> None:
        retry_after = decision.retry_after_seconds
        response = JSONResponse(
            status_code=429,
            content={
                "error": {
                    "code": "RATE_LIMITED",
                    "message": (
                        f"Too many write requests. Limit is {self._max} per {self._window}s."
                    ),
                    "details": {"retry_after_seconds": retry_after},
                }
            },
            headers={"Retry-After": str(retry_after)},
        )
        await response(scope, receive, send)


__all__ = ["WRITE_METHODS", "WriteRateLimitMiddleware"]
