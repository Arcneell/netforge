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
asyncio task. The trade-off is that a slow webhook never slows down a user
mutation, but if the process crashes before the task runs the event is lost.
For our use case (best-effort change notifications, not exactly-once event
delivery) this is the right call.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import delete, event, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.webhook import Webhook, WebhookDelivery

logger = logging.getLogger("netforge.webhooks")

# Total time budget per dispatch attempt. Webhooks should be fast — anything
# over a few seconds is almost certainly a stuck endpoint.
_DISPATCH_TIMEOUT_S = 10.0
# Rolling window for WebhookDelivery rows; cleanup happens lazily on dispatch.
_DELIVERY_RETENTION = timedelta(days=30)
# How often the lazy cleanup actually runs (don't scan on every request).
_CLEANUP_INTERVAL = timedelta(hours=6)


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

    @property
    def event_name(self) -> str:
        return f"{self.entity}.{self.action}"

    def to_payload(self) -> dict[str, Any]:
        return {
            "event": self.event_name,
            "entity": self.entity,
            "action": self.action,
            "entity_id": self.entity_id,
            "before": self.before,
            "after": self.after,
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
) -> None:
    """Called by the audit listener on each mutation. No I/O.

    The event sits in `_pending_events_var` until the surrounding session
    commits (→ promoted to `_committed_events_var`) or rolls back (→ dropped).
    """
    bucket = _pending_events_var.get()
    if bucket is None:
        bucket = []
        _pending_events_var.set(bucket)
    bucket.append(
        WebhookEvent(
            entity=entity,
            action=action,
            entity_id=entity_id,
            before=before,
            after=after,
            user_id=user_id,
        )
    )


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
    """
    try:
        async with SessionLocal() as db:
            result = await db.execute(
                select(Webhook).where(Webhook.enabled.is_(True))
            )
            webhooks: list[Webhook] = list(result.scalars().all())
            if not webhooks:
                return

            tasks: list[asyncio.Task] = []
            for ev in events:
                for webhook in webhooks:
                    if any(matches(p, ev.event_name) for p in webhook.events):
                        tasks.append(
                            asyncio.create_task(
                                _deliver_one(webhook.id, webhook.url, webhook.secret, ev)
                            )
                        )
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await _maybe_cleanup_old_deliveries(db)
    except Exception:
        # Fire-and-forget — log + swallow so we never crash the loop.
        logger.exception("webhook dispatch crashed — events dropped")


async def _deliver_one(
    webhook_id: int, url: str, secret: str, ev: WebhookEvent
) -> None:
    """Send one POST, write the delivery row + update aggregates. Never raises."""
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
    try:
        async with httpx.AsyncClient(timeout=_DISPATCH_TIMEOUT_S) as client:
            resp = await client.post(url, content=body, headers=headers)
            status_code = resp.status_code
            if status_code >= 400:
                error = f"HTTP {status_code}: {resp.text[:200]}"
    except httpx.TimeoutException:
        error = f"timeout after {_DISPATCH_TIMEOUT_S}s"
    except Exception as exc:
        # Log + persist any transport failure (DNS, connection refused, ...).
        error = f"{type(exc).__name__}: {exc}"
    latency_ms = int((time.monotonic() - started) * 1000)
    success = 200 <= status_code < 300 and error is None

    try:
        async with SessionLocal() as db:
            db.add(
                WebhookDelivery(
                    webhook_id=webhook_id,
                    event=ev.event_name,
                    payload=payload,
                    status_code=status_code,
                    success=success,
                    error=error,
                    latency_ms=latency_ms,
                )
            )
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
    except Exception:
        # Delivery row failed to persist — log and move on.
        logger.exception("failed to persist webhook delivery row")


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
    await _deliver_one(webhook.id, webhook.url, webhook.secret, test_event)
    # Read back the row we just inserted so the API can return it.
    async with SessionLocal() as db:
        result = await db.execute(
            select(WebhookDelivery)
            .where(WebhookDelivery.webhook_id == webhook.id)
            .order_by(WebhookDelivery.id.desc())
            .limit(1)
        )
        row = result.scalar_one()
    return row
