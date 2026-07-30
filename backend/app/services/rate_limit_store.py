"""Shared rate-limit counters backed by PostgreSQL.

Both limiters in the codebase — the per-IP write limiter
(`app/middleware/rate_limit.py`) and the per-user AI limiter
(`app/services/ai/rate_limit.py`) — used to keep their counters in a
process-local `deque`. That is wrong as soon as the backend runs more than
one process: with N uvicorn workers or N replicas the effective limit
becomes N x the configured value, and every restart hands every user a
fresh AI quota (the one that costs real money in LLM tokens).

Why PostgreSQL and not Redis
----------------------------
Postgres is already a hard dependency of the stack, so a self-hoster gets
the shared counter for free — no new service to deploy, monitor, secure or
back up. The cost is one extra statement on the write path (see "Cost"
below), which is cheap next to the transaction the request is about to run
anyway. Redis is the natural next step if the counter traffic ever becomes
a measurable share of DB load: the interface here (`try_consume` /
`purge_expired`) is deliberately narrow enough that a Redis implementation
would be a drop-in `INCR` + `EXPIRE`, and only the two call sites would
need rewiring.

Why tumbling buckets and not a true sliding window
--------------------------------------------------
A faithful sliding window needs one row per hit (so the count can drop
event by event), which means 60 inserts/minute/IP at the default limit,
a COUNT(*) per check, and a purge that has to keep up with the insert
rate. A tumbling bucket keeps *one row per (scope, key, window)*: the
check and the increment become a single atomic UPSERT, the table size is
bounded by the number of *active* keys rather than by the request rate,
and the purge is one indexed range delete.

The trade-off is the classic boundary burst: a client can spend its full
budget at the end of bucket k and again at the start of bucket k+1, so up
to 2x the limit over a short span straddling the boundary. That is a
bounded, transient overshoot — strictly better than the unbounded "x
number of workers" overshoot it replaces — and it is documented for
operators who care: halve `RATE_LIMIT_WINDOW_SECONDS` to halve the burst.

Concurrency
-----------
The check-and-increment is one statement:

    INSERT ... VALUES (..., hits = 1)
    ON CONFLICT (scope, bucket_key, window_start)
    DO UPDATE SET hits = rate_limit_counters.hits + 1
    WHERE rate_limit_counters.hits < :limit
    RETURNING hits

There is no application-side read-modify-write, so two workers hitting the
same key at the same instant can never lose a count: the row-level lock
Postgres takes for the `DO UPDATE` serialises them and the second one
increments the value the first one committed. The `WHERE` on the
`DO UPDATE` is what preserves the old in-memory semantics that a *rejected*
call does not consume budget: when it does not match, no row is returned
and the caller knows it was over the cap.

The bucket boundary is computed from the *server* clock
(`extract(epoch from now())`), not from each worker's clock, so replicas
with a little NTP skew still agree on which bucket they are incrementing.

Cost
----
One round trip per limited request. The statement runs on a connection
switched to AUTOCOMMIT, so there is no BEGIN/COMMIT pair around it — one
statement, one round trip, no transaction held open across the request.
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import cast

from sqlalchemy import Table, delete, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from app.models.rate_limit import RateLimitCounter

logger = logging.getLogger("netforge")

# Scope values. Namespacing the limiters inside one table keeps the
# migration count down and makes "who is being throttled right now?" a
# single query for an operator.
SCOPE_WRITE_IP = "write_ip"
SCOPE_AI_USER = "ai_user"
# Expensive GET endpoints (CSV/ZIP/PDF exports) — see
# `app/middleware/rate_limit.py`. Kept as its own scope, not folded into
# SCOPE_WRITE_IP, so an export binge doesn't eat into (or get eaten by) a
# user's write budget.
SCOPE_READ_EXPENSIVE_IP = "read_expensive_ip"

# Core table object: everything here is Core, not ORM. There is no identity
# map, no flush and no session to attach to — the whole point is one
# statement on one connection.
_TABLE = cast(Table, RateLimitCounter.__table__)


@dataclass(frozen=True, slots=True)
class Decision:
    """Outcome of one consume attempt."""

    allowed: bool
    # Hits recorded in the current bucket *after* this call. On a rejection
    # the statement returns nothing, so this is reported as the limit.
    hits: int
    # Seconds the caller should wait before retrying. Always >= 1 so a
    # `Retry-After: 0` never tells a client to hammer immediately.
    retry_after_seconds: int


def seconds_until_next_bucket(window_seconds: int, *, now: float | None = None) -> int:
    """Whole seconds left in the current tumbling bucket, floored at 1.

    Used for `Retry-After`. Computed from the local clock rather than the
    server clock on purpose: it is a hint, not an invariant, and asking the
    DB for it would cost a second round trip on the rejection path.
    """
    if window_seconds <= 0:
        return 1
    now = time.time() if now is None else now
    remaining = window_seconds - (now % window_seconds)
    return max(1, math.ceil(remaining))


async def try_consume(
    engine: AsyncEngine,
    *,
    scope: str,
    key: str,
    limit: int,
    window_seconds: int,
) -> Decision:
    """Atomically record one hit for `(scope, key)` unless it is over `limit`.

    Raises whatever the driver raises when the DB is unreachable or the
    statement fails — deciding what to do about that is the caller's job
    (the two limiters make opposite choices; see their module docstrings).
    """
    if limit <= 0:
        # A zero/negative cap means "nothing is allowed". Short-circuit
        # rather than insert a row that could never be under the cap.
        return Decision(
            allowed=False, hits=0, retry_after_seconds=seconds_until_next_bucket(window_seconds)
        )

    # Bucket boundary from the server clock: floor(epoch / window) * window.
    # `to_timestamp` returns timestamptz, matching the column type.
    bucket_epoch = func.floor(func.extract("epoch", func.now()) / window_seconds) * window_seconds
    stmt = (
        pg_insert(_TABLE)
        .values(
            scope=scope,
            bucket_key=key,
            window_start=func.to_timestamp(bucket_epoch),
            hits=1,
            expires_at=func.to_timestamp(bucket_epoch + window_seconds),
        )
        .on_conflict_do_update(
            index_elements=["scope", "bucket_key", "window_start"],
            # `_TABLE.c.hits` renders as the *existing* row's column inside
            # ON CONFLICT DO UPDATE (the proposed row would be
            # `excluded.hits`), which is exactly the atomic increment we want.
            set_={"hits": _TABLE.c.hits + 1},
            where=_TABLE.c.hits < limit,
        )
        .returning(_TABLE.c.hits)
    )

    async with engine.connect() as conn:
        # AUTOCOMMIT: the counter is intentionally outside the request's
        # transaction. A rolled-back request must still have consumed its
        # budget, otherwise a script that deliberately fails every write
        # would never be throttled.
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        row = (await conn.execute(stmt)).first()

    if row is None:
        # Conflict matched but the DO UPDATE's WHERE did not: already at
        # or above the cap for this bucket. Nothing was written, so a
        # rejected call does not extend the penalty (same semantics as the
        # in-memory window this replaces).
        return Decision(
            allowed=False,
            hits=limit,
            retry_after_seconds=seconds_until_next_bucket(window_seconds),
        )
    return Decision(
        allowed=True,
        hits=int(row[0]),
        retry_after_seconds=seconds_until_next_bucket(window_seconds),
    )


async def purge_expired(engine: AsyncEngine) -> int:
    """Delete buckets whose window has elapsed. Returns the row count.

    Rows are only useful until `expires_at`; after that they are dead
    weight that would otherwise accumulate one row per (scope, key, window)
    forever — the DB-side equivalent of the memory leak the old in-process
    GC sweeps existed to prevent.
    """
    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        result = await conn.execute(
            delete(_TABLE).where(_TABLE.c.expires_at <= func.now())
        )
    return result.rowcount or 0


# How often a worker bothers running the purge. Same lazy-cleanup idiom as
# the `webhook_deliveries` purge in `services/webhooks.py` and the expired
# `sessions` purge in `auth/sessions.py`: no background task, just an
# occasional sweep hung off a path that runs often enough. With N workers
# the sweep runs N times per interval, which is harmless (the second one
# deletes nothing).
PURGE_INTERVAL_SECONDS = 600.0

_last_purge_at: float | None = None
_purge_lock = Lock()


async def maybe_purge_expired(engine: AsyncEngine) -> None:
    """Run `purge_expired` at most once per `PURGE_INTERVAL_SECONDS`.

    Never raises: the purge is housekeeping, and failing a user request
    because dead counter rows could not be swept would be absurd.
    """
    global _last_purge_at
    now = time.monotonic()
    with _purge_lock:
        if _last_purge_at is not None and now - _last_purge_at < PURGE_INTERVAL_SECONDS:
            return
        _last_purge_at = now
    try:
        deleted = await purge_expired(engine)
        if deleted:
            logger.debug("rate_limit.purge deleted=%d", deleted)
    except Exception:
        logger.warning("rate_limit.purge failed", exc_info=True)


def reset_purge_clock() -> None:
    """Test hook — forget when the last purge ran."""
    global _last_purge_at
    _last_purge_at = None


class CircuitBreaker:
    """Trips after one failure, stays open for `cooldown_seconds`.

    Without it, a Postgres outage would make every single limited request
    pay a connection timeout before falling back. One failure is enough to
    trip: the counter statement is a sub-millisecond UPSERT, so a failure
    means the DB is unreachable, not that we were unlucky.
    """

    __slots__ = ("_cooldown", "_lock", "_opened_at")

    def __init__(self, cooldown_seconds: float) -> None:
        self._cooldown = cooldown_seconds
        self._opened_at: float | None = None
        self._lock = Lock()

    def is_open(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return False
            if time.monotonic() - self._opened_at >= self._cooldown:
                # Cooldown elapsed — let the next call probe the DB again.
                self._opened_at = None
                return False
            return True

    def record_failure(self) -> None:
        with self._lock:
            self._opened_at = time.monotonic()

    def record_success(self) -> None:
        with self._lock:
            self._opened_at = None


class InProcessWindows:
    """The legacy per-process sliding window, kept as a degradation path.

    This is the exact algorithm both limiters used before the counters
    moved to Postgres: a `deque` of hit timestamps per key, trimmed to the
    window on every read. It is still the right fallback when the shared
    counter is unavailable, and still the right implementation when an
    operator explicitly opts out of the DB round trip
    (`RATE_LIMIT_STORE=memory`) on a single-worker deployment.

    Its known limitation is the whole reason the DB store exists: N
    processes each enforce the limit independently, so the effective cap is
    N x `limit`.
    """

    __slots__ = ("_gc_every", "_hits", "_lock", "_since_gc")

    def __init__(self, *, gc_every: int = 1024) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = Lock()
        # Amortised GC: sweeping every N consumes keeps the per-call cost at
        # O(keys / N) instead of the O(keys) a "sweep whenever the dict is
        # big" gate degrades to when a scan keeps every bucket busy.
        self._gc_every = gc_every
        self._since_gc = 0

    def consume(self, key: str, *, limit: int, window_seconds: int) -> Decision:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                # The oldest in-window hit is the one that has to age out
                # before a new call fits.
                retry_after = max(1, int(bucket[0] + window_seconds - now))
                return Decision(allowed=False, hits=len(bucket), retry_after_seconds=retry_after)
            bucket.append(now)
            hits = len(bucket)
            self._since_gc += 1
            if self._since_gc >= self._gc_every:
                self._since_gc = 0
                self._gc_locked(cutoff)
        return Decision(
            allowed=True,
            hits=hits,
            retry_after_seconds=seconds_until_next_bucket(window_seconds),
        )

    def _gc_locked(self, cutoff: float) -> None:
        """Drop keys whose deque is empty once trimmed. Caller holds the lock.

        Without this, every key that ever hit the limiter leaks a deque —
        a slow memory leak on an internet-facing edge and an amplification
        surface for a low-rate scan probing from many addresses.
        """
        stale = []
        for k, bucket in self._hits.items():
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if not bucket:
                stale.append(k)
        for k in stale:
            self._hits.pop(k, None)

    def clear(self) -> None:
        """Test hook — drop every tracked key."""
        with self._lock:
            self._hits.clear()
            self._since_gc = 0


__all__ = [
    "SCOPE_AI_USER",
    "SCOPE_READ_EXPENSIVE_IP",
    "SCOPE_WRITE_IP",
    "CircuitBreaker",
    "Decision",
    "InProcessWindows",
    "maybe_purge_expired",
    "purge_expired",
    "reset_purge_clock",
    "seconds_until_next_bucket",
    "try_consume",
]
