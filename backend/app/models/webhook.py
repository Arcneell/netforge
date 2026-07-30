"""Outbound webhooks — operator-defined HTTP subscribers for entity changes.

How it works:
  - Every mutation that the audit log captures also fires a webhook event
    named `{entity}.{action}` (e.g. `port.update`, `site.create`).
  - Each `Webhook` row has a list of event patterns it subscribes to. The
    pattern `*` matches everything; `port.*` matches every port event;
    `port.update` matches exact.
  - When the request that produced the mutation succeeds (status < 400),
    a background task POSTs a JSON body to `url`, signed with HMAC-SHA256
    of the body using `secret` (header `X-Netforge-Signature`).
  - Every attempt produces one `WebhookDelivery` row for observability.

The `secret` is generated on create and displayed **once** (same pattern
as `ApiToken.token_hash`). The DB stores the raw secret because the
sender side needs it on every dispatch — there is no offline verification
trick that would let us hash it.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# --- Outbox --------------------------------------------------------------
#
# `WebhookOutbox` closes the durability gap described in
# `services/webhooks.py`'s module docstring: the event queue that lives
# between "mutation committed" and "dispatch fired" used to be pure Python
# (a ContextVar), so a process crash in that window lost the event for
# good. Every committed mutation now also gets a row here, written on the
# SAME `Connection`/transaction as the mutation itself (see
# `services/audit.py::_write_audit_row`, which calls
# `services/webhooks.py::write_outbox_row` right next to the `audit_log`
# insert it already does) — so the row and the mutation either both commit
# or both roll back together, exactly like the audit log.
#
# The fast path (dispatch immediately after commit, in-process) marks
# `dispatched_at` on success and is the common case. `attempts` /
# `last_error` only start moving once the catch-up sweep
# (`services/webhooks.py::_sweep_outbox_once`) has to step in — a crash
# between commit and the fast dispatch, or the fast dispatch itself
# raising.


class Webhook(Base):
    __tablename__ = "webhooks"
    __table_args__ = (
        UniqueConstraint("name", name="webhooks_name_uniq"),
        Index("webhooks_enabled_idx", "enabled"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    secret: Mapped[str] = mapped_column(String(64), nullable=False)
    # JSONB list of event-pattern strings: ["*"], ["port.*"], ["site.create",
    # "site.update"], ... Matched against `{entity}.{action}`.
    events: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Aggregate counters updated on each dispatch. Cheap monitoring without
    # scanning `webhook_deliveries`.
    total_deliveries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status_code: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class WebhookDelivery(Base):
    """One attempt at delivering a webhook event.

    Kept on a rolling window — the cleanup task in `services/webhooks.py`
    trims rows older than 30 days so this table stays small.
    """

    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        Index("webhook_deliveries_webhook_idx", "webhook_id", "created_at"),
        Index("webhook_deliveries_created_at_idx", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    webhook_id: Mapped[int] = mapped_column(
        ForeignKey("webhooks.id", ondelete="CASCADE"),
        nullable=False,
    )
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    # The body that was POSTed — kept verbatim for replay/debug.
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # 0 means "never got a response" (DNS, connection refused, timeout).
    status_code: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class WebhookOutbox(Base):
    """One row per committed mutation event, written in the same
    transaction as the mutation — the durable handoff between "committed"
    and "dispatched". See the module-level comment near the top of this
    file for the full rationale.

    `event_type` is the same `{entity}.{action}` string as
    `WebhookEvent.event_name` / `WebhookDelivery.event`; `entity` /
    `entity_id` are denormalised out of it purely so an operator can filter
    the table without parsing the string. `payload` is the exact dict
    `WebhookEvent.to_payload()` produced (already redacted) — replaying it
    verbatim keeps a retried delivery byte-identical to what the first
    attempt would have sent.
    """

    __tablename__ = "webhook_outbox"
    __table_args__ = (
        # Supports the sweep's "undispatched, oldest first" scan without a
        # seq scan once the table has any real volume.
        Index("webhook_outbox_undispatched_idx", "dispatched_at", "created_at"),
        # Supports the purge's "dispatched, older than retention" range delete.
        Index("webhook_outbox_dispatched_at_idx", "dispatched_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
