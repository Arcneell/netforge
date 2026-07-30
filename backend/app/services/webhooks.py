"""Outbound webhooks — dispatch entity-change events to operator URLs.

Wired into the audit listener: every CRUD that the audit log records also
queues a webhook event into a request-scoped ContextVar. SQLAlchemy
session-level `after_commit` / `after_rollback` events then promote the
events to a "committed" bucket — or drop them on rollback. The ASGI
middleware reads from that committed bucket at end-of-request and fires
deliveries as a fire-and-forget asyncio task.

Why route through commit/rollback events rather than the HTTP status code:
the audit listeners fire on flush (Codex P1 on PR #62). Some write paths
intentionally flush and roll back while still returning 2xx — the CSV
import does this for `dry_run=true` and on partial failures. Gating on
HTTP status would have notified subscribers about mutations that never
actually committed. Hooking into the session lifecycle anchors dispatch
to the real persistence boundary.

We never block the request on dispatch — it always runs as a fire-and-forget
asyncio task. The trade-off used to be that a slow webhook never slows down a
user mutation, but if the process crashed before the task ran the event was
lost for good — there was nothing durable between "mutation committed" and
"dispatch fired" besides an in-memory ContextVar.

`webhook_outbox` (app/models/webhook.py) closes that gap: `write_outbox_row`
persists each event on the SAME `Connection`/transaction as the mutation
(called from `services/audit.py::_write_audit_row`, right next to the
`audit_log` insert it already does), so the row and the mutation commit or
roll back together. The fire-and-forget dispatch above is now the *fast
path* — it still fires immediately after commit for low latency, but on
success it marks the outbox row `dispatched_at` instead of just trusting
that dispatch happened. `_sweep_outbox_once` is a lightweight background
loop (started from the FastAPI lifespan, same as `services/ai/scheduler.py`)
that catches anything the fast path missed — a crash between commit and
dispatch, or the dispatch attempt itself raising — with capped exponential
backoff and a Postgres advisory lock so multiple replicas don't all retry
the same row.

For our use case (best-effort change notifications, not exactly-once event
delivery to every subscriber) at-least-once delivery of the EVENT to the
fan-out stage is enough — per-subscriber HTTP retries remain deliberately
out of scope (see `_deliver_one`'s docstring: one attempt, no retry, the
failure is recorded in `WebhookDelivery` for the operator).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
import secrets
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx
from sqlalchemy import delete, event, insert, select, text, update
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models.webhook import Webhook, WebhookDelivery, WebhookOutbox
from app.services.audit import redact_sensitive
from app.utils.ssrf import UnsafeOutboundURL, safe_post

logger = logging.getLogger("netforge.webhooks")

# Total time budget per dispatch attempt. Webhooks should be fast — anything
# over a few seconds is almost certainly a stuck endpoint.
_DISPATCH_TIMEOUT_S = 10.0
# Rolling window for WebhookDelivery rows; cleanup happens lazily on dispatch.
_DELIVERY_RETENTION = timedelta(days=30)
# How often the lazy cleanup actually runs (don't scan on every request).
_CLEANUP_INTERVAL = timedelta(hours=6)
# Cap on simultaneous deliveries per dispatch batch. `_deliver_one` opens its
# own `SessionLocal()` to persist the delivery row (and another implicitly
# via the HTTP call), so an unbounded `asyncio.gather` over every
# event x webhook pair — a single mutation with N subscribed webhooks, or a
# bulk import that queues dozens of events — can open dozens of connections
# at once and starve the pool for every other request. Five in flight is
# plenty for the fire-and-forget, best-effort delivery this module promises.
_DISPATCH_CONCURRENCY = 5


@dataclass
class WebhookEvent:
    """A pending dispatch — collected during a request, flushed on commit."""

    entity: str
    action: str
    entity_id: int | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    user_id: int | None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    # Set by `write_outbox_row` once the corresponding `webhook_outbox` row
    # is persisted. `None` means either the row hasn't been written yet
    # (shouldn't happen for real mutations — `_write_audit_row` writes it
    # synchronously before this event is queued) or this `WebhookEvent` was
    # built outside the outbox path entirely (`send_test_event`'s synthetic
    # ping never touches the outbox). Dispatch uses it to know which outbox
    # rows to mark `dispatched_at` for; `None` means "nothing to mark".
    outbox_id: int | None = field(default=None, compare=False)

    @property
    def event_name(self) -> str:
        return f"{self.entity}.{self.action}"

    def to_payload(self) -> dict[str, Any]:
        return {
            "event": self.event_name,
            "entity": self.entity,
            "action": self.action,
            "entity_id": self.entity_id,
            # `before`/`after` already come from the audit listener's
            # redacted `changes` dict, but re-applying `redact_sensitive`
            # here is cheap and keeps this payload safe even if a future
            # caller builds a `WebhookEvent` from an un-redacted source.
            "before": None if self.before is None else redact_sensitive(self.before),
            "after": None if self.after is None else redact_sensitive(self.after),
            "user_id": self.user_id,
            "occurred_at": self.occurred_at.isoformat(),
        }


# Two request-scoped buckets:
#   _pending_events_var  — queued by audit listeners on flush, awaiting the
#                          session's commit/rollback verdict.
#   _committed_events_var — promoted from pending by the session's
#                           after_commit hook; consumed by the ASGI
#                           middleware at end of request.
# Both are reset per asyncio task (= per request).
_pending_events_var: ContextVar[list[WebhookEvent] | None] = ContextVar(
    "webhook_pending_events", default=None
)
_committed_events_var: ContextVar[list[WebhookEvent] | None] = ContextVar(
    "webhook_committed_events", default=None
)

_last_cleanup_at: datetime | None = None


def queue_event(
    entity: str,
    action: str,
    entity_id: int | None,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    user_id: int | None,
) -> WebhookEvent:
    """Called by the audit listener on each mutation. No I/O.

    The event sits in `_pending_events_var` until the surrounding session
    commits (→ promoted to `_committed_events_var`) or rolls back (→ dropped).

    Returns the queued `WebhookEvent` so the caller (`services/audit.py`)
    can hand it to `write_outbox_row` on the same `Connection` — the two
    calls together are what make the outbox row and the ContextVar entry
    describe the exact same event.
    """
    bucket = _pending_events_var.get()
    if bucket is None:
        bucket = []
        _pending_events_var.set(bucket)
    ev = WebhookEvent(
        entity=entity,
        action=action,
        entity_id=entity_id,
        before=before,
        after=after,
        user_id=user_id,
    )
    bucket.append(ev)
    return ev


def write_outbox_row(connection: Connection, event: WebhookEvent) -> None:
    """Persist `event` into `webhook_outbox` on the SAME `Connection` (and
    therefore the same transaction) as the mutation that produced it.

    Called from `services/audit.py::_write_audit_row` right next to its
    `insert(AuditLog)` call — the two inserts share one `Connection`, so a
    rollback of the mutation rolls back this row too, and a commit persists
    both atomically. That's the entire durability guarantee: by the time
    the caller's session commits, the event is already durable in
    `webhook_outbox`, independent of whether the fast dispatch path (or the
    process itself) survives long enough to fire it.

    Uses `RETURNING id` (sync `Connection.execute`, same as
    `_write_audit_row`'s `insert(AuditLog)`) so the row's id can be stashed
    on `event.outbox_id` — the dispatcher needs it to mark the row
    `dispatched_at` after a successful fan-out.
    """
    result = connection.execute(
        insert(WebhookOutbox)
        .values(
            event_type=event.event_name,
            entity=event.entity,
            entity_id=event.entity_id,
            # Round-trip through json.dumps/loads for the same reason
            # `_write_audit_row` does it for `audit_log.changes`: guarantee
            # no non-JSON-serialisable value slipped into the payload dict.
            payload=json.loads(json.dumps(event.to_payload(), default=str)),
        )
        .returning(WebhookOutbox.id)
    )
    event.outbox_id = result.scalar_one()


def take_pending() -> list[WebhookEvent]:
    """Drain the pending queue without committing it — used by tests and by
    the ASGI middleware on uncaught exceptions to discard never-committed
    events."""
    bucket = _pending_events_var.get()
    if not bucket:
        return []
    _pending_events_var.set([])
    return bucket


def take_committed() -> list[WebhookEvent]:
    """Drain the committed queue — used by the ASGI middleware to fire
    deliveries at end of request."""
    bucket = _committed_events_var.get()
    if not bucket:
        return []
    _committed_events_var.set([])
    return bucket


def _promote_pending_to_committed() -> None:
    """Move every pending event into the committed bucket. Called when the
    surrounding SQLAlchemy session commits successfully."""
    pending = _pending_events_var.get()
    if not pending:
        return
    _pending_events_var.set([])
    committed = _committed_events_var.get()
    if committed is None:
        committed = []
        _committed_events_var.set(committed)
    committed.extend(pending)


def _drop_pending() -> None:
    """Discard the pending queue. Called when the surrounding session rolls
    back so we never ping subscribers about rolled-back mutations."""
    _pending_events_var.set([])


# Register the session-lifecycle hooks once. SQLAlchemy fires these on the
# underlying sync Session even when the caller uses AsyncSession — that's
# why we listen on Session, not AsyncSession.
@event.listens_for(Session, "after_commit")
def _on_session_commit(_session: Session) -> None:
    _promote_pending_to_committed()


@event.listens_for(Session, "after_rollback")
def _on_session_rollback(_session: Session) -> None:
    _drop_pending()


@event.listens_for(Session, "after_soft_rollback")
def _on_session_soft_rollback(_session: Session, _previous_state: Any) -> None:
    # SAVEPOINT releases / nested rollbacks also discard their queue — the
    # audit rows were inserted under that savepoint and won't survive.
    _drop_pending()


def generate_secret() -> str:
    """64-char URL-safe random — fits the model's String(64) column."""
    return secrets.token_urlsafe(48)[:64]


def sign_body(secret: str, body: bytes) -> str:
    """HMAC-SHA256 hex digest in the GitHub-style `sha256=...` form."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def matches(pattern: str, event_name: str) -> bool:
    """Pattern semantics:
      `*`               -> match anything
      `{entity}.*`      -> match every action on entity
      `{entity}.create` -> exact match
    Patterns are stored lowercased; we lowercase the event too defensively."""
    pattern = pattern.lower()
    event_name = event_name.lower()
    if pattern == "*":
        return True
    if pattern.endswith(".*"):
        return event_name.startswith(pattern[:-1])
    return pattern == event_name


# Strong references to in-flight dispatch tasks so the event loop doesn't
# garbage-collect them mid-flight (RUF006). They self-remove on done.
_background_tasks: set[asyncio.Task] = set()


def dispatch_committed_in_background() -> None:
    """Schedule a dispatch of committed events as a fire-and-forget task.
    Safe to call when nothing is committed — no task is created.

    Called by the ASGI middleware once the request has completed; we use
    the committed bucket (populated by the session's after_commit hook)
    rather than the raw pending queue, so subscribers never see events
    from rolled-back transactions.
    """
    events = take_committed()
    if not events:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Not in an event loop (shouldn't happen from the middleware).
        return
    task = loop.create_task(_dispatch_events(events))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _dispatch_events(events: list[WebhookEvent]) -> None:
    """One-shot fan-out: load matching webhooks, POST in parallel.

    The lookup query lives here (not at queue time) so toggling a webhook
    on/off takes effect for the very next request in every worker process
    — no cross-worker cache to sync (Codex P2 on PR #62).

    This is the outbox's *fast path*: on success (the fan-out itself didn't
    raise — individual webhook POSTs can still fail, that's what
    `WebhookDelivery` is for) it marks every event's `webhook_outbox` row
    `dispatched_at`, so `_sweep_outbox_once` never has to touch it. A crash
    anywhere in this function skips the marking entirely — the outer
    `except` swallows it (fire-and-forget), and the row is left for the
    catch-up sweep to retry later.
    """
    try:
        async with SessionLocal() as db:
            result = await db.execute(
                select(Webhook).where(Webhook.enabled.is_(True))
            )
            registered: list[Webhook] = list(result.scalars().all())
            if registered:
                semaphore = asyncio.Semaphore(_DISPATCH_CONCURRENCY)
                tasks: list[asyncio.Task] = [
                    asyncio.create_task(
                        _deliver_one_bounded(
                            semaphore, webhook.id, webhook.url, webhook.secret, ev
                        )
                    )
                    for ev in events
                    for webhook in registered
                    if any(matches(p, ev.event_name) for p in webhook.events)
                ]
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
            # Reached regardless of whether anything matched — an event
            # with zero subscribers is still "dispatched" (there was
            # nothing to send), and the row shouldn't linger for the sweep
            # to pick up forever.
            await _mark_outbox_dispatched(db, events)
            await _maybe_cleanup_old_deliveries(db)
    except Exception:
        # Fire-and-forget — log + swallow so we never crash the loop.
        logger.exception("webhook dispatch crashed — events dropped")


async def _mark_outbox_dispatched(db: AsyncSession, events: list[WebhookEvent]) -> None:
    """Mark the `webhook_outbox` rows behind `events` as dispatched.

    Skips events with no `outbox_id` (the synthetic `send_test_event` ping
    never gets one) and no-ops entirely — no query, no commit — when none
    of the batch has one, so tests / callers that build bare `WebhookEvent`s
    without going through `write_outbox_row` see no behaviour change.
    """
    ids = [ev.outbox_id for ev in events if ev.outbox_id is not None]
    if not ids:
        return
    await db.execute(
        update(WebhookOutbox)
        .where(WebhookOutbox.id.in_(ids))
        .values(dispatched_at=datetime.now(UTC), attempts=WebhookOutbox.attempts + 1)
    )
    await db.commit()


class DeliverableEvent(Protocol):
    """What the delivery path actually needs off an event.

    Two things reach `_deliver_one`: a live `WebhookEvent` on the fast path,
    and a `_ReplayEvent` rebuilt from an outbox row on the retry path. Neither
    is a subclass of the other and neither should be — the replay deliberately
    carries the already-redacted payload verbatim instead of re-deriving it.
    Naming the two attributes they share keeps that duck-typing checkable
    rather than papering over it with a cast.
    """

    @property
    def event_name(self) -> str: ...

    def to_payload(self) -> dict[str, Any]: ...


async def _deliver_one_bounded(
    semaphore: asyncio.Semaphore, webhook_id: int, url: str, secret: str, ev: DeliverableEvent
) -> WebhookDelivery:
    """Same as `_deliver_one`, gated by `semaphore` so a batch with many
    event x webhook pairs doesn't open unbounded concurrent DB sessions."""
    async with semaphore:
        return await _deliver_one(webhook_id, url, secret, ev)


async def _deliver_one(
    webhook_id: int, url: str, secret: str, ev: DeliverableEvent
) -> WebhookDelivery:
    """Send one POST, write the delivery row + update aggregates. Never raises.

    Returns the `WebhookDelivery` row describing the attempt. When
    persisting the row fails, the returned object is transient (`id` is
    None) but still carries the attempt's outcome — `send_test_event`
    relies on that to answer the `/test` endpoint without re-querying.

    One attempt per event, no retry: webhooks here are best-effort change
    notifications (see the module docstring), so a failed POST is recorded
    in the delivery log for the operator instead of being retried.
    """
    payload = ev.to_payload()
    body = json.dumps(payload, default=str, separators=(",", ":")).encode("utf-8")
    signature = sign_body(secret, body)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Netforge-Webhook/1.0",
        "X-Netforge-Event": ev.event_name,
        "X-Netforge-Signature": signature,
        "X-Netforge-Delivery": secrets.token_hex(8),
    }

    status_code = 0
    error: str | None = None
    started = time.monotonic()
    # `safe_post` bundles the SSRF guard with DNS pinning: it resolves the
    # hostname once, refuses private / loopback / metadata targets (unless
    # the operator opted in) and connects to the vetted IP — so a rebinding
    # DNS server can't swap in an internal address between validation and
    # connection. Without this, an admin (or any holder of an admin API
    # token) can point a webhook at http://postgres:5432,
    # http://169.254.169.254/..., or the backend's own /api/, and the first
    # 200 bytes of the response leak into WebhookDelivery.error.
    try:
        resp = await safe_post(
            url,
            content=body,
            headers=headers,
            timeout=_DISPATCH_TIMEOUT_S,
            allow_private=get_settings().webhook_allow_private_targets,
        )
        status_code = resp.status_code
        if status_code >= 400:
            error = f"HTTP {status_code}: {resp.text[:200]}"
    except UnsafeOutboundURL as exc:
        error = f"UnsafeOutboundURL: {exc}"
    except httpx.TimeoutException:
        error = f"timeout after {_DISPATCH_TIMEOUT_S}s"
    except Exception as exc:
        # Log + persist any transport failure (DNS, connection refused, ...).
        error = f"{type(exc).__name__}: {exc}"
    latency_ms = int((time.monotonic() - started) * 1000)
    success = 200 <= status_code < 300 and error is None

    delivery = WebhookDelivery(
        webhook_id=webhook_id,
        event=ev.event_name,
        payload=payload,
        status_code=status_code,
        success=success,
        error=error,
        latency_ms=latency_ms,
    )
    try:
        async with SessionLocal() as db:
            db.add(delivery)
            await db.execute(
                update(Webhook)
                .where(Webhook.id == webhook_id)
                .values(
                    total_deliveries=Webhook.total_deliveries + 1,
                    total_failures=Webhook.total_failures + (0 if success else 1),
                    last_delivery_at=datetime.now(UTC),
                    last_status_code=status_code or None,
                    last_error=None if success else error,
                )
            )
            await db.commit()
            await db.refresh(delivery)
    except Exception:
        # Delivery row failed to persist — log and move on. The transient
        # object still describes the attempt for the caller.
        logger.exception("failed to persist webhook delivery row")
    return delivery


async def _maybe_cleanup_old_deliveries(db: AsyncSession) -> None:
    """Trim WebhookDelivery rows older than the retention window. Runs at most
    once per `_CLEANUP_INTERVAL` to keep dispatch-path overhead near zero."""
    global _last_cleanup_at
    now = datetime.now(UTC)
    if _last_cleanup_at is not None and now - _last_cleanup_at < _CLEANUP_INTERVAL:
        return
    _last_cleanup_at = now
    cutoff = now - _DELIVERY_RETENTION
    await db.execute(delete(WebhookDelivery).where(WebhookDelivery.created_at < cutoff))
    await db.commit()


async def send_test_event(webhook: Webhook) -> WebhookDelivery:
    """Synthetic ping used by the `/test` endpoint. Persists a delivery row
    so the operator sees the result in the UI alongside real events."""
    test_event = WebhookEvent(
        entity="webhook",
        action="test",
        entity_id=webhook.id,
        before=None,
        after={"hello": "from netforge"},
        user_id=None,
    )
    delivery = await _deliver_one(webhook.id, webhook.url, webhook.secret, test_event)
    if delivery.id is None:
        # Persisting the row failed (transient DB error) — the POST itself
        # may still have gone out, so answer with the attempt's outcome
        # instead of crashing the endpoint with a 500. `id=0` marks the
        # synthetic, never-persisted row for the response model.
        delivery.id = 0
        delivery.created_at = datetime.now(UTC)
    return delivery


# --- Outbox catch-up sweep ---------------------------------------------------
#
# The fast path (`_dispatch_events`, above) handles the overwhelming
# majority of events immediately after commit. This section is the safety
# net for what it misses: a process crash between commit and the
# fire-and-forget task running, or the fast dispatch itself raising before
# it could mark the row `dispatched_at`. A lightweight background loop
# (started from the FastAPI lifespan, same wiring as
# `services/ai/scheduler.py`) periodically re-scans `webhook_outbox` for
# rows nobody has marked dispatched yet.

# Rows younger than this are left alone even if `dispatched_at` is still
# NULL — the fast path for the very same commit is either about to run or
# already running, and there's no point in the sweep racing it. This also
# doubles as the first retry's backoff step, see `_cumulative_backoff`.
_OUTBOX_RETRY_BACKOFF: tuple[timedelta, ...] = (
    timedelta(seconds=30),
    timedelta(minutes=2),
    timedelta(minutes=10),
)
# After this many attempts (fast path + sweep retries combined) a row is
# abandoned: it keeps its `last_error` for the operator but the sweep query
# excludes it (`attempts < _OUTBOX_MAX_ATTEMPTS`) so it stops being retried
# forever. Purge (below) eventually removes it once/if it's ever dispatched;
# an abandoned row that never dispatches is left for an operator to notice
# via `last_error`, same trade-off `WebhookDelivery` makes for a single
# failed HTTP attempt.
_OUTBOX_MAX_ATTEMPTS = 5
# How often the sweep loop wakes up. Cheap query (indexed, bounded LIMIT)
# so a short interval doesn't cost much, and it keeps the worst-case delay
# for a missed event low.
_OUTBOX_SWEEP_INTERVAL_SECONDS = 15
# Cap on rows processed per sweep pass — bounds worst-case work per tick the
# same way `_DISPATCH_CONCURRENCY` bounds fan-out concurrency.
_OUTBOX_SWEEP_BATCH_LIMIT = 100

# Rolling retention for dispatched `webhook_outbox` rows — mirrors the
# `webhook_deliveries` / `ai_run_logs` lazy-cleanup idiom, anchored on the
# sweep loop since that's the outbox's own long-lived background context
# (parallel to how the AI scheduler anchors `ai_run_logs`' purge on its
# loop instead of a request path).
_OUTBOX_RETENTION = timedelta(days=7)
_OUTBOX_CLEANUP_INTERVAL = timedelta(hours=6)
_last_outbox_cleanup_at: datetime | None = None

# Advisory-lock key for the anti-overlap guard below. Single-bigint form
# (like `services/users.py`'s cold-start bootstrap lock) rather than the
# two-int classid/objid form `services/ai/scheduler.py` uses for its
# per-schedule lock — the sweep locks the ENTIRE pass, not one row at a
# time, so there's only ever one lock to take, not one per row.
_OUTBOX_SWEEP_LOCK_KEY = 0x4E465F574F  # "NF_WO" (NetForge Webhook Outbox), arbitrary but stable

_sweep_task: asyncio.Task | None = None


def _cumulative_backoff(attempts: int) -> timedelta:
    """Total time since `created_at` required before the `attempts`-th
    retry is allowed to fire.

    `attempts` counts attempts already made (fast path counts as one on
    success — see `_mark_outbox_dispatched` — so in practice this function
    is almost always evaluated at `attempts == 0`, meaning "the fast path
    never even ran"). Steps beyond `_OUTBOX_RETRY_BACKOFF`'s length reuse
    the last (longest) step rather than growing further, so a row that's
    already used up its schedule gets retried every 10 minutes instead of
    escalating indefinitely — `_OUTBOX_MAX_ATTEMPTS` is what eventually
    stops it, not an ever-growing wait.

    There's no `last_attempt_at` column (the schema is deliberately just
    id/event_type/entity/entity_id/payload/created_at/dispatched_at/
    attempts/last_error), so backoff is anchored on `created_at` and
    accumulated across the schedule rather than measured from "now minus
    the previous attempt" — simpler storage, and for a best-effort catch-up
    sweep the difference is immaterial.
    """
    total = timedelta()
    steps = len(_OUTBOX_RETRY_BACKOFF)
    for i in range(attempts + 1):
        total += _OUTBOX_RETRY_BACKOFF[min(i, steps - 1)]
    return total


def _is_due_for_retry(created_at: datetime, attempts: int, now: datetime) -> bool:
    """Whether an undispatched outbox row is old enough for its next retry.

    `attempts >= _OUTBOX_MAX_ATTEMPTS` is a hard stop — the row is
    abandoned, `_sweep_outbox_once`'s query already filters these out, but
    this function pins the same rule so tests can exercise it directly.
    """
    if attempts >= _OUTBOX_MAX_ATTEMPTS:
        return False
    return now - created_at >= _cumulative_backoff(attempts)


@dataclass
class _ReplayEvent:
    """Adapts a `WebhookOutbox` row back into the shape `_deliver_one`
    expects (`.event_name` + `.to_payload()`), without reconstructing a
    full `WebhookEvent` or re-running redaction. The stored `payload`
    column IS the exact, already-redacted dict the original dispatch
    attempt would have sent — replaying it verbatim keeps a retried
    delivery byte-identical to what the first attempt sent."""

    event_name: str
    payload: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return self.payload


def _dialect_name(db: AsyncSession) -> str:
    """Best-effort detection of the underlying DB dialect.

    Duplicated locally rather than imported from `services/ai/scheduler.py`
    or `services/users.py` — same reasoning both of those give for not
    sharing this helper: it's three lines, and importing it would reach
    into another service's private helper for no real benefit. Returns ""
    for mocks / anything that doesn't expose the
    `sync_session.bind.dialect` chain, which the caller treats as "not
    Postgres" and skips the advisory lock — never worse than baseline.
    """
    try:
        # `bind` is typed as Engine | Connection | None; a None bind raises
        # AttributeError here, which is exactly the "not Postgres" fallback.
        name = db.sync_session.bind.dialect.name  # type: ignore[union-attr]
    except AttributeError:
        return ""
    return str(name) if isinstance(name, str) else ""


async def _try_acquire_outbox_sweep_lock(lock_db: AsyncSession) -> bool:
    """Best-effort cross-replica / cross-worker mutex for one sweep pass.

    Multi-replica deploys each run their own sweep loop against the same
    `webhook_outbox` table; without a lock, two replicas can both pick up
    the same due row in the same tick and both fire duplicate deliveries.
    `pg_try_advisory_xact_lock` is non-blocking and scoped to `lock_db`'s
    own transaction — same pattern as
    `services/ai/scheduler.py::_try_acquire_schedule_lock`, including the
    "separate session from the one doing the work" rule: the work session
    commits partway through (once per retried row, see
    `_sweep_outbox_once`), and an xact-scoped lock taken on THAT session
    would be released by its first commit, long before the pass finishes.

    Non-Postgres backends (sqlite, unit-test mocks) skip the lock — same
    fallback as both locks above.
    """
    if _dialect_name(lock_db) != "postgresql":
        return True
    result = await lock_db.execute(
        text("SELECT pg_try_advisory_xact_lock(:key)").bindparams(key=_OUTBOX_SWEEP_LOCK_KEY)
    )
    return bool(result.scalar())


async def _maybe_cleanup_dispatched_outbox_rows(db: AsyncSession) -> None:
    """Trim dispatched `webhook_outbox` rows older than the retention
    window. Runs at most once per `_OUTBOX_CLEANUP_INTERVAL`, anchored on
    the sweep loop (see the module-level comment above this section)."""
    global _last_outbox_cleanup_at
    now = datetime.now(UTC)
    if (
        _last_outbox_cleanup_at is not None
        and now - _last_outbox_cleanup_at < _OUTBOX_CLEANUP_INTERVAL
    ):
        return
    _last_outbox_cleanup_at = now
    cutoff = now - _OUTBOX_RETENTION
    await db.execute(
        delete(WebhookOutbox).where(
            WebhookOutbox.dispatched_at.is_not(None),
            WebhookOutbox.dispatched_at < cutoff,
        )
    )
    await db.commit()


async def _sweep_outbox_once() -> None:
    """One pass of the catch-up sweep.

    Takes the advisory lock, scans for undispatched rows old enough for
    their next retry, replays each through the same `_deliver_one_bounded`
    path the fast dispatch uses, and updates `attempts` / `last_error` /
    `dispatched_at` per row. Every exception is caught per-row so one dead
    endpoint doesn't stop the rest of the batch — mirrors
    `services/ai/scheduler.py::_loop`'s per-schedule isolation.
    """
    async with SessionLocal() as lock_db:
        try:
            acquired = await _try_acquire_outbox_sweep_lock(lock_db)
        except Exception:
            logger.exception(
                "outbox sweep: advisory lock check failed — proceeding without it"
            )
            acquired = True
        if not acquired:
            logger.info("outbox sweep: locked by another worker/replica — skipping this tick")
            return

        now = datetime.now(UTC)
        async with SessionLocal() as db:
            candidates = (
                (
                    await db.execute(
                        select(WebhookOutbox)
                        .where(
                            WebhookOutbox.dispatched_at.is_(None),
                            WebhookOutbox.attempts < _OUTBOX_MAX_ATTEMPTS,
                            WebhookOutbox.created_at < now - _OUTBOX_RETRY_BACKOFF[0],
                        )
                        .order_by(WebhookOutbox.created_at)
                        .limit(_OUTBOX_SWEEP_BATCH_LIMIT)
                    )
                )
                .scalars()
                .all()
            )
            due = [
                row for row in candidates if _is_due_for_retry(row.created_at, row.attempts, now)
            ]
            if not due:
                return

            result = await db.execute(select(Webhook).where(Webhook.enabled.is_(True)))
            registered: list[Webhook] = list(result.scalars().all())
            semaphore = asyncio.Semaphore(_DISPATCH_CONCURRENCY)

            for row in due:
                try:
                    tasks = [
                        asyncio.create_task(
                            _deliver_one_bounded(
                                semaphore,
                                webhook.id,
                                webhook.url,
                                webhook.secret,
                                _ReplayEvent(event_name=row.event_type, payload=row.payload),
                            )
                        )
                        for webhook in registered
                        if any(matches(p, row.event_type) for p in webhook.events)
                    ]
                    if tasks:
                        await asyncio.gather(*tasks)
                    # `_deliver_one` never raises (it records HTTP/transport
                    # failures in `WebhookDelivery` instead) — reaching here
                    # means the fan-out itself didn't crash, which is all
                    # the outbox promises. Per-subscriber failures stay
                    # exactly where they already were: `webhook_deliveries`.
                    row.dispatched_at = now
                    row.last_error = None
                except Exception as exc:
                    row.last_error = f"{type(exc).__name__}: {exc}"
                row.attempts += 1

            await db.commit()
            await _maybe_cleanup_dispatched_outbox_rows(db)
    # Exiting the outer `async with` closes `lock_db`, rolling back its
    # (otherwise untouched) transaction — that's what releases the lock.


async def _sweep_loop() -> None:
    """The forever-running catch-up sweep task."""
    logger.info(
        "webhook outbox sweep loop started (every %ss)", _OUTBOX_SWEEP_INTERVAL_SECONDS
    )
    while True:
        try:
            await _sweep_outbox_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("webhook outbox sweep iteration crashed — continuing")
        try:
            await asyncio.sleep(_OUTBOX_SWEEP_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            raise


def start_outbox_sweep() -> None:
    """Spawn the background sweep loop. Safe to call multiple times — the
    second call is a no-op once the first task is alive.

    No-op when `webhook_outbox_sweep_enabled` is False — the fast dispatch
    path and the durable outbox write both keep working, just without the
    retry loop backing them up."""
    global _sweep_task
    settings = get_settings()
    if not settings.webhook_outbox_sweep_enabled:
        logger.info("webhook outbox sweep disabled by WEBHOOK_OUTBOX_SWEEP_ENABLED=false")
        return
    if _sweep_task is not None and not _sweep_task.done():
        return
    _sweep_task = asyncio.create_task(_sweep_loop(), name="webhook-outbox-sweep")


async def stop_outbox_sweep() -> None:
    """Cancel the background sweep loop. Called from the FastAPI lifespan
    on shutdown."""
    global _sweep_task
    if _sweep_task is None:
        return
    _sweep_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _sweep_task
    _sweep_task = None
