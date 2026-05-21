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
