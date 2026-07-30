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
import json
import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionLocal  # alias kept locally below for readability
from app.models.ai import (
    AIRunKind,
    AIRunLog,
    AISchedule,
    InfraInsight,
    InsightSeverity,
)
from app.services.ai.advisor import AdvisorReport, run_advisor
from app.services.ai.suggest_links import ScanReport, run_suggest_links

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

# Rolling retention for `ai_run_logs`, mirroring the 30-day window that
# `services/webhooks.py` applies to `webhook_deliveries`. The cleanup is
# throttled so the minute-tick loop doesn't scan the table on every pass.
_RUN_LOG_RETENTION = timedelta(days=30)
_RUN_LOG_CLEANUP_INTERVAL = timedelta(hours=6)
_last_run_log_cleanup_at: datetime | None = None

# Advisory-lock namespace for the anti-overlap guard below. `classid`
# distinguishes this lock family from unrelated advisory locks elsewhere in
# the app (see `services/users.py`'s cold-start bootstrap lock, which uses
# the single-bigint form instead of the two-int form used here); `objid` is
# the schedule row's id, so each schedule gets its own independent lock.
_SCHEDULE_LOCK_CLASSID = 0x41495F53  # "AI_S" as bytes, arbitrary but stable


def _dialect_name(db: AsyncSession) -> str:
    """Best-effort detection of the underlying DB dialect.

    Mirrors `services/users.py::_dialect_name` — duplicated locally rather
    than imported so this module doesn't reach into another service's
    private helper. Returns "" for mocks / anything that doesn't expose the
    `sync_session.bind.dialect` chain, which the caller treats as "not
    Postgres" and skips the lock entirely (never worse than baseline).
    """
    try:
        # `bind` is typed as Engine | Connection | None; a None bind raises
        # AttributeError here, which is exactly the "not Postgres" fallback.
        name = db.sync_session.bind.dialect.name  # type: ignore[union-attr]
    except AttributeError:
        return ""
    return str(name) if isinstance(name, str) else ""


async def _try_acquire_schedule_lock(lock_db: AsyncSession, schedule_id: int) -> bool:
    """Best-effort cross-replica / cross-worker mutex for one schedule's run.

    Multi-replica deploys each run their own scheduler loop against the same
    `ai_schedules` table; without a lock, two replicas can both see the same
    schedule as due in the same minute and both fire the LLM call (and, for
    the advisor, both attempt the webhook POST). `pg_try_advisory_xact_lock`
    is non-blocking (returns false instead of waiting) and scoped to
    `lock_db`'s own transaction — the caller keeps that transaction open
    (uncommitted) for as long as it wants the lock held, then lets it roll
    back on session close to release it. Deliberately a SEPARATE session
    from the one doing the actual work (`db` in `_run_one`), because that
    one commits partway through — an xact-scoped lock taken there would be
    released by the first `db.commit()`, well before the webhook fires.

    Non-Postgres backends (sqlite test fixtures) skip the lock — same
    fallback as the bootstrap lock in `services/users.py`.
    """
    if _dialect_name(lock_db) != "postgresql":
        return True
    result = await lock_db.execute(
        text("SELECT pg_try_advisory_xact_lock(:classid, :objid)").bindparams(
            classid=_SCHEDULE_LOCK_CLASSID, objid=schedule_id
        )
    )
    return bool(result.scalar())


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
    failing provider every minute. The caller (`_loop`) additionally wraps
    each call to this function in its own try/except so a bookkeeping
    failure (e.g. `db.commit()` itself raising, or `_maybe_notify` raising)
    can't abort the rest of the batch — only the LLM call used to be
    guarded here, which meant an exception anywhere else propagated out of
    this function and skipped every remaining due schedule for the tick.
    """
    settings = get_settings()
    if not settings.ai_enabled:
        # Admin disabled AI globally — leave `last_run_at` untouched so the
        # settings UI doesn't claim a run that never happened and the first
        # real run after re-enabling fires immediately instead of waiting
        # for the next interval. The outer loop already paces itself via
        # the minute-tick sleep, so we don't busy-loop on this branch.
        return

    # Anti-overlap guard: a dedicated session holds the advisory lock for
    # the whole run (see `_try_acquire_schedule_lock`'s docstring for why it
    # can't be `db`). Failing to even check the lock (e.g. a transient
    # connection error) fails OPEN — proceeding without the lock is no
    # worse than the pre-existing behaviour, and strictly better than a
    # scheduler that stops firing entirely because the lock check itself
    # is flaky.
    async with SessionLocal() as lock_db:
        try:
            acquired = await _try_acquire_schedule_lock(lock_db, schedule.id)
        except Exception:
            logger.exception(
                "scheduler: advisory lock check failed for schedule id=%s — "
                "proceeding without it",
                schedule.id,
            )
            acquired = True
        if not acquired:
            logger.info(
                "scheduler: schedule id=%s is locked by another worker/replica — "
                "skipping this tick",
                schedule.id,
            )
            return

        previous_run_id = schedule.last_run_id
        # Both branches below produce a different report dataclass; only
        # `.run_id` is read from it here, so the name is declared wide enough
        # to hold either.
        report: AdvisorReport | ScanReport
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
    # Exiting the `async with` closes `lock_db`, rolling back its (otherwise
    # untouched) transaction — that's what releases the advisory lock.


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

    def keys(rows: Sequence[InfraInsight]) -> set[tuple[str, str]]:
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


def _format_for_chat_provider(url: str, generic: dict[str, Any]) -> dict[str, Any]:
    """Translate the generic envelope into the shape the receiver expects.

    Slack / Mattermost / Teams reject a bare `{event, findings}` payload —
    they all need a top-level `text` (Slack/Mattermost) or `{title, sections}`
    (Teams). We detect the URL host and rewrite accordingly; an unknown URL
    gets the generic envelope as-is, which works for relays / custom HTTP
    endpoints that expect it.
    """
    findings = generic.get("findings") or []
    lines = [
        f"*[{f['severity'].upper()}]* {f['title']} ({f['category']})"
        for f in findings[:10]
    ]
    summary = (
        f"NetForge AI advisor: {len(findings)} new finding(s) at or above "
        f"`{generic.get('threshold', 'warning')}`"
    )
    body_md = summary + ("\n" + "\n".join(lines) if lines else "")
    # Use the parsed hostname rather than `substring in url` — otherwise
    # an attacker-controlled URL like `https://attacker.com/?hooks.slack.com`
    # flips the formatting branch even though the receiver is not Slack.
    # In isolation that's just a payload shape mismatch, but it weakens
    # the assumption operators have about which host gets which shape.
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()

    def _host_in(suffixes: tuple[str, ...]) -> bool:
        return any(host == s or host.endswith("." + s) for s in suffixes)

    if _host_in(("hooks.slack.com",)) or "mattermost" in host:
        # Slack/Mattermost both accept the legacy `text` shape — Mattermost
        # adopted it for compatibility with Slack integrations. Mattermost
        # has no canonical host suffix, so we keep the substring check
        # there (typical self-hosted Mattermost URLs contain "mattermost").
        return {"text": body_md}
    if _host_in(("office.com", "outlook.com")) or "webhook.office" in host:
        # Microsoft Teams "MessageCard" — minimal viable schema.
        return {
            "@type": "MessageCard",
            "@context": "https://schema.org/extensions",
            "summary": summary,
            "themeColor": "C81E1E",
            "title": "NetForge AI advisor",
            "text": body_md,
        }
    if _host_in(("discord.com", "discordapp.com")):
        return {"content": body_md[:1900]}  # Discord caps `content` at 2000.
    # Unknown URL — assume a generic relay that consumes our envelope.
    return generic


async def _send_webhook(url: str, payload: dict[str, Any]) -> None:
    """Fire-and-log POST. We don't retry — webhook receivers are typically
    idempotent enough on title+category, and a transient failure surfaces
    in the logs for the operator to dig into.

    The body is reshaped per receiver via `_format_for_chat_provider` so
    pasting a Slack / Mattermost / Teams / Discord URL Just Works.

    Optionally signed: when `ai_webhook_signing_secret` is set, the request
    carries an `X-Netforge-Signature: sha256=<hmac>` header over the exact
    body bytes, computed with `services.webhooks.sign_body` — the same
    HMAC helper the generic `Webhook` model's deliveries already use — so a
    receiver only has to implement verification once. Unsigned (no header)
    when the secret is unset, which is the default: `ai_schedules` rows
    don't have their own per-row secret column the way `Webhook` does, so
    this is deliberately a single global secret
    (`settings.ai_webhook_signing_secret`, read via `getattr` so a stubbed
    Settings in tests without the field still no-ops instead of erroring).
    """
    if not url:
        return
    # SSRF guard — see app/utils/ssrf.py for the rationale. The scheduler
    # path uses the same admin-supplied URL surface as the webhooks
    # router so the same protection applies. `safe_post` resolves the
    # hostname once, validates the IPs and pins the connection to a vetted
    # address so a rebinding DNS server can't redirect the POST to an
    # internal target between validation and connection.
    from app.config import get_settings
    from app.services.webhooks import sign_body
    from app.utils.ssrf import UnsafeOutboundURL, safe_post

    body = _format_for_chat_provider(url, payload)
    # Serialise once so the bytes we sign are exactly the bytes we send —
    # passing `json=body` to httpx and signing a separate `json.dumps` call
    # risks the two not matching byte-for-byte (key ordering, separators).
    body_bytes = json.dumps(body, default=str, separators=(",", ":")).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    secret = getattr(get_settings(), "ai_webhook_signing_secret", None)
    if secret:
        headers["X-Netforge-Signature"] = sign_body(secret, body_bytes)
    try:
        resp = await safe_post(
            url,
            content=body_bytes,
            headers=headers,
            timeout=10.0,
            allow_private=get_settings().webhook_allow_private_targets,
        )
        resp.raise_for_status()
    except UnsafeOutboundURL as exc:
        logger.warning("AI webhook refused (SSRF guard): %s", exc)
    except Exception:
        logger.exception("webhook post failed url=%s", url)


async def _maybe_cleanup_run_logs(db: AsyncSession) -> None:
    """Trim `ai_run_logs` rows older than the retention window.

    Anchored in the scheduler loop because it's the only long-lived
    background context the AI stack has — the same reason the webhook
    dispatcher hosts the `webhook_deliveries` purge. Limitation: with
    `AI_SCHEDULER_ENABLED=false` the purge never runs; acceptable because
    without the scheduler the table only grows through manual admin calls,
    which are rate-limited to a trickle.

    The most recent successful advisor run is always kept regardless of
    age: `infra_insights` rows CASCADE-delete with their run, and the
    insights page + PDF export serve exactly that run's rows. Everything
    older loses its (superseded) insights along with the log row, and the
    `link_suggestions` / `ai_schedules` FKs are SET NULL so nothing else
    breaks.
    """
    global _last_run_log_cleanup_at
    now = datetime.now(UTC)
    if (
        _last_run_log_cleanup_at is not None
        and now - _last_run_log_cleanup_at < _RUN_LOG_CLEANUP_INTERVAL
    ):
        return
    _last_run_log_cleanup_at = now
    cutoff = now - _RUN_LOG_RETENTION
    keep_latest_advisor = (
        select(AIRunLog.id)
        .where(AIRunLog.kind == AIRunKind.advisor, AIRunLog.success.is_(True))
        .order_by(AIRunLog.created_at.desc())
        .limit(1)
    ).scalar_subquery()
    await db.execute(
        delete(AIRunLog).where(
            AIRunLog.created_at < cutoff,
            AIRunLog.id.not_in(keep_latest_advisor),
        )
    )
    await db.commit()


async def _loop() -> None:
    """The forever-running scheduler task."""
    logger.info("AI scheduler loop started (every %ss)", _LOOP_INTERVAL_SECONDS)
    while True:
        try:
            async with SessionLocal() as db:
                due = await _list_due(db, datetime.now(UTC))
                for schedule in due:
                    # Isolate each schedule from the others: `_run_one`
                    # already guards its own LLM call, but a failure in the
                    # bookkeeping around it (the `last_run_at` commit, or
                    # `_maybe_notify`) used to propagate out of this loop
                    # and silently skip every remaining due schedule for
                    # the tick (and the cleanup pass below). One schedule's
                    # bug should never starve the others.
                    try:
                        await _run_one(db, schedule)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception(
                            "scheduler: schedule id=%s kind=%s crashed outside its "
                            "own error handling — continuing with the rest",
                            schedule.id,
                            schedule.kind,
                        )
                await _maybe_cleanup_run_logs(db)
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
    call is a no-op once the first task is alive.

    No-op when `ai_scheduler_enabled` is False — the admin opted out of the
    auto-fire loop at the settings level. Manual `/insights/refresh` and
    `/suggestions/links/scan` calls still work."""
    global _TASK
    settings = get_settings()
    if not settings.ai_scheduler_enabled:
        logger.info("AI scheduler disabled by AI_SCHEDULER_ENABLED=false")
        return
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
