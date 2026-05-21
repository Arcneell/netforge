"""Outbound webhooks — dispatch entity-change events to operator URLs.

Wired into the audit listener: every CRUD that the audit log records also
queues a webhook event into a request-scoped ContextVar. After the request
completes successfully (status < 400, no exception), the ASGI middleware
flushes the queue via `dispatch_pending()`, which:

  - resolves the list of enabled `Webhook` rows whose `events` patterns
    match the queued events,
  - POSTs the body to each, signed with HMAC-SHA256 of the body using the
    webhook's `secret` (header `X-Netforge-Signature: sha256=<hex>`),
  - writes a `WebhookDelivery` row per attempt and updates the parent
    `Webhook`'s aggregate counters.

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
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

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
    """A pending dispatch — collected during a request, flushed on success."""

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


# Populated by the audit listener via `queue_event`; flushed by the
# ASGI middleware via `dispatch_pending`. Each request gets a fresh list
# because ContextVar is task-local in asyncio.
_pending_events_var: ContextVar[list[WebhookEvent] | None] = ContextVar(
    "webhook_pending_events", default=None
)

# Module-level toggle so tests can disable dispatch globally without poking
# at the model rows. Set False at app startup when no webhooks exist (cheap
# optimisation) and re-enabled by the router when a row is created.
_dispatch_enabled = True
_last_cleanup_at: datetime | None = None


def set_dispatch_enabled(enabled: bool) -> None:
    """Tests / startup can short-circuit dispatch entirely."""
    global _dispatch_enabled
    _dispatch_enabled = enabled


def queue_event(
    entity: str,
    action: str,
    entity_id: int | None,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    user_id: int | None,
) -> None:
    """Called by the audit listener on each mutation. No I/O."""
    if not _dispatch_enabled:
        return
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
    """Drain the queue for the current request — used by tests + middleware."""
    bucket = _pending_events_var.get()
    if not bucket:
        return []
    _pending_events_var.set([])
    return bucket


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


def dispatch_pending_in_background() -> None:
    """Schedule a dispatch of currently-queued events as a fire-and-forget
    task. Safe to call when nothing is pending — no task is created.

    Called by the ASGI middleware once the response is known to be 2xx/3xx.
    """
    events = take_pending()
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
    """One-shot fan-out: load matching webhooks, POST in parallel."""
    try:
        async with SessionLocal() as db:
            result = await db.execute(
                select(Webhook).where(Webhook.enabled.is_(True))
            )
            webhooks: list[Webhook] = list(result.scalars().all())
            if not webhooks:
                return

            tasks: list[asyncio.Task] = []
            for event in events:
                for webhook in webhooks:
                    if any(matches(p, event.event_name) for p in webhook.events):
                        tasks.append(
                            asyncio.create_task(
                                _deliver_one(webhook.id, webhook.url, webhook.secret, event)
                            )
                        )
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await _maybe_cleanup_old_deliveries(db)
    except Exception:
        # Fire-and-forget — log + swallow so we never crash the loop.
        logger.exception("webhook dispatch crashed — events dropped")


async def _deliver_one(
    webhook_id: int, url: str, secret: str, event: WebhookEvent
) -> None:
    """Send one POST, write the delivery row + update aggregates. Never raises."""
    payload = event.to_payload()
    body = json.dumps(payload, default=str, separators=(",", ":")).encode("utf-8")
    signature = sign_body(secret, body)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Netforge-Webhook/1.0",
        "X-Netforge-Event": event.event_name,
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
                    event=event.event_name,
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


async def refresh_dispatch_enabled() -> None:
    """Probe the DB for any enabled webhook and update the module toggle.

    Called at startup so we can short-circuit dispatch for installs that
    never use webhooks (zero overhead). Routers call it again after each
    create/update/delete so toggling a row takes effect immediately.
    """
    async with SessionLocal() as db:
        result = await db.execute(
            select(Webhook.id).where(Webhook.enabled.is_(True)).limit(1)
        )
        any_enabled = result.first() is not None
    set_dispatch_enabled(any_enabled)


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
