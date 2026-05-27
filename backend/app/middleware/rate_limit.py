"""Per-IP sliding-window rate limit on write methods.

The audit log and DB integrity already protect against accidental damage,
but a hot-looped script or a curl mistake could still flood writes and burn
through DB connections. We cap writes to N per window per IP using an
in-memory sliding window — fine for a single uvicorn worker; deferred to
Redis once the deployment scales to multiple workers (cf. docs/07-deployment.md).

Reads are never rate-limited here — the dashboard and topology views fire
several GETs per page load and we don't want to penalise normal browsing.
The CSV upload endpoint also passes through (uploads are throttled by their
own 10 MiB cap; counting them with a single hit per minute is the right
trade-off given their size).

Implementation note: this is a raw ASGI middleware, NOT a
`BaseHTTPMiddleware` subclass. Starlette's `BaseHTTPMiddleware` bridges
the response through an anyio memory stream, which silently breaks
`text/event-stream` streaming (chunks pile up until the response ends).
The raw ASGI shape pipes `(scope, receive, send)` straight through, so
SSE on `/api/ai/query/stream` actually flushes per-token.
"""

from __future__ import annotations

import time
from collections import deque
from threading import Lock

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.utils.request import client_ip

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Paths that should pass through unconditionally. Health probes must not be
# throttled, and the OAuth callback is a one-shot redirect that can briefly
# happen multiple times in legitimate flows (browser back, page reloads).
_EXEMPT_PATHS = frozenset(
    {"/api/health", "/api/auth/login", "/api/auth/callback", "/api/auth/logout"}
)


class WriteRateLimitMiddleware:
    """Raw ASGI middleware — see module docstring for why not BaseHTTPMiddleware."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_per_window: int,
        window_seconds: int,
    ) -> None:
        self.app = app
        self._max = max_per_window
        self._window = float(window_seconds)
        self._hits: dict[str, deque[float]] = {}
        self._lock = Lock()
        # Counter of writes since the last GC sweep. Sweeps run once per
        # _GC_EVERY_N writes (amortising the O(N) work), not once per
        # write past _GC_THRESHOLD — otherwise a hot-looped scan that
        # keeps N active IPs all-busy degrades each write to O(N) under
        # one mutex.
        self._writes_since_gc = 0

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
        now = time.monotonic()
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            cutoff = now - self._window
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self._max:
                retry_after = max(1, int(bucket[0] + self._window - now))
                response = JSONResponse(
                    status_code=429,
                    content={
                        "error": {
                            "code": "RATE_LIMITED",
                            "message": (
                                f"Too many write requests. "
                                f"Limit is {self._max} per {int(self._window)}s."
                            ),
                            "details": {"retry_after_seconds": retry_after},
                        }
                    },
                    headers={"Retry-After": str(retry_after)},
                )
                await response(scope, receive, send)
                return
            bucket.append(now)
            # Amortised periodic GC of empty / stale buckets. Without
            # this, every unique source IP that ever wrote leaves a
            # deque() in `_hits` forever — a slow memory leak on a
            # public-facing edge and an amplification surface for a
            # low-rate scan probing from many addresses. The sweep
            # itself is O(N); we run it at most once every _GC_EVERY_N
            # writes regardless of how big `_hits` gets, so the per-write
            # cost is O(N/_GC_EVERY_N) ≈ O(1) on average. The previous
            # gate ("sweep every write past 1024 keys") regressed every
            # write to O(N) under one mutex when an N-IP scan kept all
            # buckets busy.
            self._writes_since_gc += 1
            if self._writes_since_gc >= self._GC_EVERY_N:
                self._writes_since_gc = 0
                self._gc_locked(cutoff)

        await self.app(scope, receive, send)

    # How many writes between GC sweeps. 1024 keeps the amortised cost
    # of the O(N) sweep at ≈1/1024 per write — small enough to be
    # invisible in the request hot path on any deployment short of
    # millions of distinct active IPs.
    _GC_EVERY_N: int = 1024

    def _gc_locked(self, cutoff: float) -> None:
        """Caller must hold self._lock. Drop entries whose bucket is empty
        after `cutoff`-trimming. Bounded: at most O(N) over `_hits`, and
        amortised at one such sweep per `_GC_EVERY_N` writes.
        """
        stale: list[str] = []
        for k, bucket in self._hits.items():
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if not bucket:
                stale.append(k)
        for k in stale:
            self._hits.pop(k, None)


__all__ = ["WRITE_METHODS", "WriteRateLimitMiddleware"]
