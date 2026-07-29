"""Per-user rate limiter for AI calls, backed by a shared DB counter.

Why a separate limiter from the global write-rate-limiter:
- AI calls are inherently expensive (LLM tokens cost money).
- Limit is per-user, not per-IP — a shared-office NAT wouldn't kill one
  user's budget because another user across the room hit it.
- Window is hours, not seconds.

Where the counter lives
-----------------------
In `rate_limit_counters` (PostgreSQL), scope `ai_user`. The counter used to
be a process-local `deque`, which had two bugs that mattered *because this
limiter guards money*: with N workers/replicas every user got N x their
quota, and a restart (deploy, crash, scale event) handed everyone a fresh
quota. A one-hour window makes the restart case especially bad — a
crash-looping container effectively removes the cap. See
`app/services/rate_limit_store.py` for the schema/algorithm rationale.

Degradation policy: FAIL CLOSED
-------------------------------
If the shared counter cannot be reached, `consume_ai_quota` raises
`AIRateLimitExceeded` and the caller returns its usual 429. This is the
opposite of the write limiter's fail-open, on purpose:

- What is at stake here is spend, not availability. An AI call we cannot
  account for is an unbounded bill; a write we cannot count is, at worst,
  load on a database that is already refusing work.
- Falling back to a per-process window would silently restore exactly the
  N x quota bug this module exists to fix, and would do so at the moment
  we have the least visibility.
- The blast radius is small and self-healing: AI features are optional and
  admin-only, every AI route needs the same database for its run log and
  conversation rows anyway, and service returns as soon as the DB does.

`RATE_LIMIT_STORE=memory` opts out of the DB entirely and restores the old
per-process window — the escape hatch for a single-worker deployment (and
what the unit suite uses so it never needs a database).

`consume_ai_quota` is the only entry point, and it is async: it runs on the
application engine's pool, with no worker thread and no per-call connection.
An earlier revision exposed a synchronous `check_and_consume` that bridged
to this coroutine through a thread and a throwaway engine; every AI route
handler is async, so the bridge was deleted along with its per-call
Postgres connect.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.config import get_settings
from app.services.rate_limit_store import (
    SCOPE_AI_USER,
    InProcessWindows,
    maybe_purge_expired,
    try_consume,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger("netforge")

# Retry hint handed to a client when the counter itself is unavailable.
# Short: the outage is the reason for the 429, so we want the client back
# as soon as the DB recovers, not in an hour.
_FAIL_CLOSED_RETRY_AFTER = 30


class AIRateLimitExceeded(RuntimeError):
    """Raised when a user has used their quota for the current window."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("AI rate limit exceeded")
        self.retry_after_seconds = retry_after_seconds


# Fallback / opt-out window. Only used when RATE_LIMIT_STORE != "database".
_MEMORY = InProcessWindows()


async def consume_ai_quota(user_id: int, *, engine: AsyncEngine | None = None) -> None:
    """Record one AI call for `user_id`, raising if the user is over budget.

    Runs on the application engine's connection pool.

    Anonymous calls (user_id is None / 0) are blocked: every AI route is
    admin-only, so an unauthenticated path shouldn't reach the limiter in
    the first place. The guard here is belt-and-braces.
    """
    if not user_id:
        raise AIRateLimitExceeded(retry_after_seconds=60)
    settings = get_settings()
    limit = settings.ai_rate_limit_calls
    window = settings.ai_rate_window_seconds

    if settings.rate_limit_store != "database":
        decision = _MEMORY.consume(str(user_id), limit=limit, window_seconds=window)
        if not decision.allowed:
            raise AIRateLimitExceeded(retry_after_seconds=decision.retry_after_seconds)
        return

    if engine is None:
        from app.db import engine as app_engine

        engine = app_engine

    try:
        decision = await try_consume(
            engine,
            scope=SCOPE_AI_USER,
            key=str(user_id),
            limit=limit,
            window_seconds=window,
        )
    except Exception as exc:
        # Fail closed — see the module docstring. Log loudly: an operator
        # seeing 429s on every AI call needs to know it is the counter,
        # not the quota.
        logger.warning(
            "ai_rate_limit.fail_closed user_id=%s reason=counter_unavailable",
            user_id,
            exc_info=True,
        )
        raise AIRateLimitExceeded(retry_after_seconds=_FAIL_CLOSED_RETRY_AFTER) from exc

    await maybe_purge_expired(engine)
    if not decision.allowed:
        raise AIRateLimitExceeded(retry_after_seconds=decision.retry_after_seconds)


__all__ = ["AIRateLimitExceeded", "consume_ai_quota"]
