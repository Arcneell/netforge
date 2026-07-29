"""shared rate-limit counters

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-29

Both rate limiters used to count in a process-local `deque`: the per-IP
write limiter (`app/middleware/rate_limit.py`) and the per-user AI limiter
(`app/services/ai/rate_limit.py`). That is only correct for a single
process. With N uvicorn workers or N replicas the effective cap becomes
N x the configured value — a runaway script simply spreads its load across
workers — and every restart resets the AI quota, which is the one that
costs real money in LLM tokens (a one-hour window plus a crash-looping
container effectively removes the cap).

This migration adds the table both limiters now share. PostgreSQL rather
than Redis because Postgres is already a hard dependency of the stack:
self-hosters get the shared counter without deploying, securing and backing
up a second service. Redis is the documented next step if counter traffic
ever becomes a measurable share of DB load — the application-side interface
(`app/services/rate_limit_store.py`) is narrow enough that a Redis backend
would be `INCR` + `EXPIRE` behind the same two functions.

Shape: tumbling buckets, one row per (scope, key, window)
---------------------------------------------------------
The alternative — one row per hit, so a true sliding window can drop events
one by one — costs 60 inserts/minute/IP at the default limit, a COUNT(*)
per check, and a purge that has to keep up with the request rate. A
tumbling bucket keeps a single row per active key per window: check and
increment collapse into one atomic UPSERT, table size is bounded by the
number of *active* keys instead of by traffic, and the purge is one indexed
range delete.

The trade-off is the classic boundary burst: a client can spend its whole
budget at the end of one bucket and again at the start of the next, so up
to 2x the limit over a short span straddling the boundary. Bounded and
transient — strictly better than the unbounded "x number of workers"
overshoot it replaces — and an operator who cares can halve
RATE_LIMIT_WINDOW_SECONDS to halve the burst.

Columns
-------
- `scope`        — which limiter owns the row ("write_ip", "ai_user"). One
                   table, no key collisions between limiters, and "who is
                   being throttled right now?" is one query.
- `bucket_key`   — the limited principal: client IP, or a stringified user
                   id. String(255) covers both plus whatever a third
                   limiter would key on.
- `window_start` — bucket boundary, floored to a multiple of the window
                   length and computed from the *server* clock so replicas
                   with NTP skew still agree on which bucket they hit.
- `hits`         — count for that bucket.
- `expires_at`   — `window_start + window`, denormalised purely so the
                   purge is `DELETE ... WHERE expires_at <= now()` without
                   the SQL having to know each scope's window length.

Indexes
-------
- Primary key `(scope, bucket_key, window_start)` — every lookup is an
  equality match on exactly those three columns, performed as part of the
  upsert, so the PK btree *is* the hot-path index. No secondary index on
  the key columns would ever be used.
- `ix_rate_limit_counters_expires_at` — supports the purge range delete;
  without it every sweep is a seq scan of the whole table.

Purge
-----
Rows are dead weight past `expires_at`. `rate_limit_store.maybe_purge_expired`
sweeps them at most once per 10 minutes per worker, hung off the write path
— the same lazy-cleanup idiom as the expired-`sessions` purge in
`auth/sessions.py`, the `webhook_deliveries` purge in `services/webhooks.py`
and the `ai_run_logs` trim in `services/ai/scheduler.py`. No background task
to supervise, and with N workers the extra sweeps simply delete nothing.

Concurrency
-----------
The application never does a read-modify-write. Every hit is:

    INSERT ... VALUES (..., 1)
    ON CONFLICT (scope, bucket_key, window_start)
    DO UPDATE SET hits = rate_limit_counters.hits + 1
    WHERE rate_limit_counters.hits < :limit
    RETURNING hits

Two workers incrementing the same key at the same instant serialise on the
row lock Postgres takes for the DO UPDATE, so no count is lost. The WHERE
on the DO UPDATE preserves the in-memory semantics that a *rejected* call
does not consume budget: it returns no row, which is how the caller knows
it was over the cap.

Downgrade drops the table. Nothing references it and the counters are
ephemeral by construction, so the only consequence is that in-flight
windows reset — the same thing a restart used to do on every deploy.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_counters",
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("bucket_key", sa.String(length=255), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "scope", "bucket_key", "window_start", name="rate_limit_counters_pkey"
        ),
    )
    op.create_index(
        "ix_rate_limit_counters_expires_at",
        "rate_limit_counters",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_rate_limit_counters_expires_at", table_name="rate_limit_counters")
    op.drop_table("rate_limit_counters")
