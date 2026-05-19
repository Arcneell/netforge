"""Aggregations over `ai_run_logs` for the AI Usage dashboard.

We compute totals at request-time. Volumes are modest (one row per LLM call,
admin-only feature, single-instance deploy) — no need for a materialised view
or a pre-aggregated table. If usage grows past ~100k rows / month, swap to a
daily rollup table populated by a nightly job.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import AIRunKind, AIRunLog
from app.services.ai.pricing import estimate_cost_usd


@dataclass
class UsageTotal:
    calls: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    success: int
    failure: int
    avg_latency_ms: int


@dataclass
class UsageBucket:
    """Generic aggregate keyed by a dimension (day, kind, provider, …)."""

    key: str
    totals: UsageTotal


@dataclass
class UsageReport:
    """Top-level response shape consumed by the UI."""

    window_days: int
    started_at: datetime
    total: UsageTotal
    by_day: list[UsageBucket]
    by_kind: list[UsageBucket]
    by_provider: list[UsageBucket]


def _zero_total() -> UsageTotal:
    return UsageTotal(0, 0, 0, 0.0, 0, 0, 0)


def _accumulate(t: UsageTotal, row: AIRunLog) -> None:
    """Mutate `t` in place — keeps the loops below cheap and readable."""
    t.calls += 1
    t.prompt_tokens += row.prompt_tokens or 0
    t.completion_tokens += row.completion_tokens or 0
    t.cost_usd += estimate_cost_usd(
        provider=row.provider,
        model=row.model,
        prompt_tokens=row.prompt_tokens or 0,
        completion_tokens=row.completion_tokens or 0,
    )
    if row.success:
        t.success += 1
    else:
        t.failure += 1


def _finalise(t: UsageTotal, latencies: list[int]) -> UsageTotal:
    if latencies:
        t.avg_latency_ms = int(sum(latencies) / len(latencies))
    # Round the cost so the UI doesn't render 0.00021487 — accountancy-side
    # precision belongs in a real billing pipeline, not this estimate.
    t.cost_usd = round(t.cost_usd, 4)
    return t


def _format_day(dt: datetime) -> str:
    """ISO date in UTC for the day bucket — the UI is responsible for
    rendering it in the operator's local timezone if needed."""
    return dt.astimezone(UTC).date().isoformat()


async def build_usage_report(db: AsyncSession, *, days: int) -> UsageReport:
    """Fetch the last `days` days of `ai_run_logs` and bucket them.

    Bounds: `days` is clamped to [1, 365] by the route layer — we trust the
    contract here. A 365-day fetch on a busy instance reads ~10-30k rows,
    which is comfortable for one query + one Python pass.
    """
    started_at = datetime.now(UTC) - timedelta(days=days)
    rows = (
        (
            await db.execute(
                select(AIRunLog)
                .where(AIRunLog.created_at >= started_at)
                .order_by(AIRunLog.created_at.asc())
            )
        )
        .scalars()
        .all()
    )

    total = _zero_total()
    total_latencies: list[int] = []
    by_day: dict[str, tuple[UsageTotal, list[int]]] = {}
    by_kind: dict[str, tuple[UsageTotal, list[int]]] = {}
    by_provider: dict[str, tuple[UsageTotal, list[int]]] = {}

    def _bucket(d: dict, key: str) -> tuple[UsageTotal, list[int]]:
        if key not in d:
            d[key] = (_zero_total(), [])
        return d[key]

    for row in rows:
        _accumulate(total, row)
        total_latencies.append(row.latency_ms or 0)

        day_key = _format_day(row.created_at)
        t_day, lat_day = _bucket(by_day, day_key)
        _accumulate(t_day, row)
        lat_day.append(row.latency_ms or 0)

        kind_key = row.kind.value if isinstance(row.kind, AIRunKind) else str(row.kind)
        t_kind, lat_kind = _bucket(by_kind, kind_key)
        _accumulate(t_kind, row)
        lat_kind.append(row.latency_ms or 0)

        provider_key = row.provider or "unknown"
        t_prov, lat_prov = _bucket(by_provider, provider_key)
        _accumulate(t_prov, row)
        lat_prov.append(row.latency_ms or 0)

    _finalise(total, total_latencies)
    # Fill every day in the window with a zero bucket before sorting — the
    # sparkline must not skip quiet days, otherwise a window with calls on
    # day 1 and day 30 only would render those two points as adjacent.
    today = datetime.now(UTC).date()
    cursor = started_at.astimezone(UTC).date()
    while cursor <= today:
        key = cursor.isoformat()
        if key not in by_day:
            by_day[key] = (_zero_total(), [])
        cursor += timedelta(days=1)
    # Sort day buckets ascending so the UI can draw a sparkline directly.
    day_items = sorted(by_day.items(), key=lambda kv: kv[0])
    return UsageReport(
        window_days=days,
        started_at=started_at,
        total=total,
        by_day=[UsageBucket(k, _finalise(v[0], v[1])) for k, v in day_items],
        by_kind=[UsageBucket(k, _finalise(v[0], v[1])) for k, v in by_kind.items()],
        by_provider=[UsageBucket(k, _finalise(v[0], v[1])) for k, v in by_provider.items()],
    )


async def _total_calls_in_window(db: AsyncSession, *, days: int) -> int:
    """Cheap counter used by smoke tests + the "no usage" empty state."""
    started_at = datetime.now(UTC) - timedelta(days=days)
    row = (
        await db.execute(
            select(func.count(AIRunLog.id)).where(AIRunLog.created_at >= started_at)
        )
    ).scalar_one()
    return int(row or 0)
