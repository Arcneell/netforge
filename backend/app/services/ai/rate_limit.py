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
        counter = _USERS.setdefault(user_id, _UserCounter())
    counter.consume(limit=settings.ai_rate_limit_calls, window=settings.ai_rate_window_seconds)
