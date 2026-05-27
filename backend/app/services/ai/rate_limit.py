"""Per-user in-memory rate limiter for AI calls.

Simple sliding-window counter — good enough for a single-instance deploy.
For multi-replica deployments swap to slowapi/Redis (same interface).

Why a separate limiter from the global write-rate-limiter:
- AI calls are inherently expensive (LLM tokens cost money).
- Limit is per-user, not per-IP — a shared-office NAT wouldn't kill one
  user's budget because another user across the room hit it.
- Window is hours, not seconds.
"""

from __future__ import annotations

import time
from collections import deque
from threading import Lock

from app.config import get_settings


class AIRateLimitExceeded(RuntimeError):
    """Raised when a user has used their quota for the current window."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("AI rate limit exceeded")
        self.retry_after_seconds = retry_after_seconds


class _UserCounter:
    """Tracks call timestamps for one user."""

    __slots__ = ("_calls", "_lock")

    def __init__(self) -> None:
        self._calls: deque[float] = deque()
        self._lock = Lock()

    def consume(self, *, limit: int, window: int) -> None:
        now = time.monotonic()
        cutoff = now - window
        with self._lock:
            # Drop expired entries up front so the deque doesn't grow.
            while self._calls and self._calls[0] < cutoff:
                self._calls.popleft()
            if len(self._calls) >= limit:
                # Oldest in-window entry is the one that has to expire
                # before a new call is allowed.
                retry_after = int(self._calls[0] - cutoff)
                raise AIRateLimitExceeded(retry_after_seconds=max(retry_after, 1))
            self._calls.append(now)


_USERS: dict[int, _UserCounter] = {}
_USERS_LOCK = Lock()
# Counter of consumes since the last GC sweep. Same pattern as the
# write-rate-limit middleware: a long-lived process onboarding/offboarding
# users over months would otherwise accumulate `_UserCounter`s in `_USERS`
# forever (each one holding a Lock + deque). Sweep amortised at one
# per _GC_EVERY_N calls so the per-consume cost stays O(1).
_GC_EVERY_N = 1024
_consumes_since_gc = 0


def check_and_consume(user_id: int) -> None:
    """Increment the counter for `user_id`, raising if over budget.

    Anonymous calls (user_id is None / 0) are blocked — every AI route is
    admin-only in Phase 1, so an unauthenticated path shouldn't reach the
    limiter in the first place. The guard here is belt-and-braces.
    """
    if not user_id:
        raise AIRateLimitExceeded(retry_after_seconds=60)
    settings = get_settings()
    with _USERS_LOCK:
        # Sweep BEFORE setdefault so a just-created counter is never
        # collected as "empty" before its first consume() runs. Codex
        # P2 on #97 caught the inverted order: a 1024th call for a
        # brand-new user would create the counter, then `_gc_idle_counters`
        # would see it as empty (no entries yet) and drop it from
        # `_USERS`. The current call still ran on the detached counter,
        # but the NEXT call for that user got a fresh counter,
        # undercounting the quota by 1 per sweep cycle.
        global _consumes_since_gc
        _consumes_since_gc += 1
        if _consumes_since_gc >= _GC_EVERY_N:
            _consumes_since_gc = 0
            _gc_idle_counters(window=settings.ai_rate_window_seconds)
        counter = _USERS.setdefault(user_id, _UserCounter())
    counter.consume(limit=settings.ai_rate_limit_calls, window=settings.ai_rate_window_seconds)


def _gc_idle_counters(window: int) -> None:
    """Drop counters whose call deque is empty after window-trimming.
    Caller must hold _USERS_LOCK.

    Locking discipline: we touch each `_UserCounter._lock` to peek-trim
    its deque, then read `len(_calls)` under that same lock. Acquiring
    a child lock while holding the parent is safe here because no other
    code path holds the child lock while needing the parent.
    """
    now = time.monotonic()
    cutoff = now - window
    stale: list[int] = []
    for uid, counter in _USERS.items():
        with counter._lock:
            while counter._calls and counter._calls[0] < cutoff:
                counter._calls.popleft()
            if not counter._calls:
                stale.append(uid)
    for uid in stale:
        _USERS.pop(uid, None)
