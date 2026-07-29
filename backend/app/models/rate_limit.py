"""Shared rate-limit counters.

One row per (scope, key, time bucket). The table is the cross-process
substitute for the per-worker `deque`s the two limiters used to keep in
memory — see `app/services/rate_limit_store.py` for the atomic UPSERT that
drives it and for the design rationale (why Postgres, why tumbling buckets).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RateLimitCounter(Base):
    """Hit counter for one (scope, key) pair inside one time bucket.

    The primary key `(scope, bucket_key, window_start)` is also the only
    lookup path: every read is an equality match on all three columns,
    performed as part of the `INSERT ... ON CONFLICT` upsert, so the PK
    btree is the index the hot path needs and no secondary index on the
    key columns is warranted.

    `expires_at` (= `window_start + window`) exists purely so the purge is
    a single indexed range delete that does not have to know each scope's
    window length. Without it, deleting stale rows would mean scanning the
    whole table or hard-coding per-scope windows in SQL.
    """

    __tablename__ = "rate_limit_counters"
    __table_args__ = (
        # Purge support: `DELETE ... WHERE expires_at <= now()`.
        Index("ix_rate_limit_counters_expires_at", "expires_at"),
    )

    # Which limiter owns the row ("write_ip", "ai_user"). Keeps the two
    # limiters in one table without their keys ever colliding.
    scope: Mapped[str] = mapped_column(String(32), primary_key=True)
    # The limited principal: a client IP for the write limiter, a stringified
    # user id for the AI limiter. String(255) is wide enough for both and for
    # whatever a third limiter would key on later.
    bucket_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    # Start of the tumbling window this row counts, floored to a multiple of
    # the window length so every worker computes the same bucket boundary.
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)

    hits: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = ["RateLimitCounter"]
