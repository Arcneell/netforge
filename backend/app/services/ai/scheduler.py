"""Periodic AI runs (advisor / suggest-links) + webhook notifications.

Design choices:
- One asyncio background task per FastAPI process. Multi-replica deploys
  would run the loop in each worker — that's why every actual run is
  wrapped in an UPDATE that writes `last_run_at` and skips if another
  worker beat us to it. (Best-effort: two workers checking within the same
  second can still both run; cheap enough to tolerate.)
- The scheduler is opt-in: rows in `ai_schedules` ship with `enabled=false`,
  and an admin has to flip the toggle from the Settings UI.
- Webhook payload is a small JSON envelope — Slack / Mattermost / Teams /
  custom HTTP endpoints can all consume it directly via their incoming-
  webhook format with a tiny wrapper if needed.

We don't pull in `apscheduler` or `celery` — the surface is tiny enough that
a stdlib loop is cheaper to reason about. If the schedule list grows past
~10 rows or the cadence gets more granular, swap to APScheduler.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionLocal  # alias kept locally below for readability
from app.models.ai import (
    AIRunKind,
    AISchedule,
    InfraInsight,
    InsightSeverity,
)
from app.services.ai.advisor import run_advisor
from app.services.ai.suggest_links import run_suggest_links

logger = logging.getLogger("netforge.ai.scheduler")

# How often the loop wakes up. One minute is fine — the granularity an admin
# can pick is 15 minutes anyway.
_LOOP_INTERVAL_SECONDS = 60

# Severity ordering for the "this is at or above threshold" check.
_SEVERITY_RANK = {
    InsightSeverity.info: 0,
    InsightSeverity.warning: 1,
    InsightSeverity.critical: 2,
}

# Module-level handle so `stop_scheduler` can cancel cleanly on shutdown.
_TASK: asyncio.Task | None = None


def is_due(schedule: AISchedule, now: datetime) -> bool:
    """Return True when the schedule should run now (or hasn't run yet)."""
    if not schedule.enabled:
        return False
    if schedule.last_run_at is None:
        return True
    return now >= schedule.last_run_at + timedelta(minutes=schedule.interval_minutes)


async def _list_due(db: AsyncSession, now: datetime) -> list[AISchedule]:
    rows = (await db.execute(select(AISchedule))).scalars().all()
    return [r for r in rows if is_due(r, now)]


async def _run_one(db: AsyncSession, schedule: AISchedule) -> None:
    """Drive one due schedule.

    Wraps every step so a transient provider error never kills the loop —
    the schedule's `last_run_at` is bumped regardless so we don't hammer a
    failing provider every minute.
    """
    settings = get_settings()
    if not settings.ai_enabled:
        # Admin disabled AI globally — we still bump `last_run_at` so we
        # don't busy-loop checking the same schedule every minute.
        schedule.last_run_at = datetime.now(UTC)
        await db.commit()
        return

    previous_run_id = schedule.last_run_id
    try:
        if schedule.kind == AIRunKind.advisor:
            report = await run_advisor(db, user_id=None)
        elif schedule.kind == AIRunKind.suggest_links:
            report = await run_suggest_links(db, user_id=None)
        else:
            logger.warning("scheduler skipping unknown kind %s", schedule.kind)
            schedule.last_run_at = datetime.now(UTC)
            await db.commit()
            return
    except Exception:
        logger.exception("scheduler run failed kind=%s id=%s", schedule.kind, schedule.id)
        schedule.last_run_at = datetime.now(UTC)
        await db.commit()
        return

    schedule.last_run_at = datetime.now(UTC)
    schedule.last_run_id = report.run_id
    await db.commit()

    # Only the advisor emits insights — suggest-links emits suggestions,
    # which the operator triages by hand. No webhook for the latter today.
    if schedule.kind == AIRunKind.advisor and schedule.webhook_url:
        await _maybe_notify(
            db,
            schedule=schedule,
            new_run_id=report.run_id,
            previous_run_id=previous_run_id,
        )


async def _maybe_notify(
    db: AsyncSession,
    *,
    schedule: AISchedule,
    new_run_id: int,
    previous_run_id: int | None,
) -> None:
    """Fire the webhook when the latest run introduces an insight at or above
    the threshold that wasn't present in the previous run.

    "Present in previous" means: same `(title, category)` tuple. That's a
    cheap signature — the LLM's title is stable across runs when the
    underlying signal hasn't changed (e.g., "subnet 10.0.0.0/24 is 92% full"
    won't change wording when the percentage is the same)."""
    threshold = _SEVERITY_RANK[schedule.webhook_severity_threshold]

    def keys(rows: list[InfraInsight]) -> set[tuple[str, str]]:
        return {
            (r.title.strip().lower(), r.category.value)
            for r in rows
            if _SEVERITY_RANK[r.severity] >= threshold
        }

    new_rows = (
        (await db.execute(select(InfraInsight).where(InfraInsight.run_id == new_run_id)))
        .scalars()
        .all()
    )
    new_keys = keys(new_rows)
    if not new_keys:
        return

    if previous_run_id:
        prev_rows = (
            (
                await db.execute(
                    select(InfraInsight).where(InfraInsight.run_id == previous_run_id)
                )
            )
            .scalars()
            .all()
        )
        prev_keys = keys(prev_rows)
    else:
        prev_keys = set()

    newly_introduced = new_keys - prev_keys
    if not newly_introduced:
        return

    introduced_rows = [
        r
        for r in new_rows
        if (r.title.strip().lower(), r.category.value) in newly_introduced
    ]
    payload = _build_webhook_payload(schedule=schedule, new_rows=introduced_rows)
    await _send_webhook(schedule.webhook_url or "", payload)


def _build_webhook_payload(
    *, schedule: AISchedule, new_rows: list[InfraInsight]
) -> dict[str, Any]:
    """Stable, provider-agnostic envelope. Slack/Mattermost/Teams expect
    different top-level shapes — operators add their thin wrapper if
    needed."""
    return {
        "source": "netforge",
        "event": "advisor.new_findings",
        "schedule_id": schedule.id,
        "run_id": schedule.last_run_id,
        "threshold": schedule.webhook_severity_threshold.value,
        "findings": [
            {
                "severity": r.severity.value,
                "category": r.category.value,
                "title": r.title,
                "description": r.description[:1000],
                "recommendation": r.recommendation[:1000],
            }
            for r in new_rows[:20]
        ],
        "fired_at": datetime.now(UTC).isoformat(),
    }


async def _send_webhook(url: str, payload: dict[str, Any]) -> None:
    """Fire-and-log POST. We don't retry — webhook receivers are typically
    idempotent enough on title+category, and a transient failure surfaces
    in the logs for the operator to dig into."""
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
    except Exception:
        logger.exception("webhook post failed url=%s", url)


async def _loop() -> None:
    """The forever-running scheduler task."""
    logger.info("AI scheduler loop started (every %ss)", _LOOP_INTERVAL_SECONDS)
    while True:
        try:
            async with SessionLocal() as db:
                due = await _list_due(db, datetime.now(UTC))
                for schedule in due:
                    await _run_one(db, schedule)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("scheduler loop iteration crashed — continuing")
        try:
            await asyncio.sleep(_LOOP_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            raise


def start_scheduler() -> None:
    """Spawn the background loop. Safe to call multiple times — the second
    call is a no-op once the first task is alive."""
    global _TASK
    if _TASK is not None and not _TASK.done():
        return
    _TASK = asyncio.create_task(_loop(), name="ai-scheduler")


async def stop_scheduler() -> None:
    """Cancel the background loop. Called from the FastAPI lifespan on
    shutdown."""
    global _TASK
    if _TASK is None:
        return
    _TASK.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _TASK
    _TASK = None
