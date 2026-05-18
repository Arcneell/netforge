"""AI integration models — run-log + link suggestions."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AIRunKind(str, Enum):
    """Top-level kind of AI call — used to gate feature toggles and rate limits."""

    suggest_links = "suggest_links"
    advisor = "advisor"
    nl_query = "nl_query"


class AIRunLog(Base):
    """One row per call to an AI provider — for cost tracking + debugging.

    Stored independently from the audit log because audit rows live on the
    entity timeline (one row per CRUD action), whereas AI calls are
    cross-cutting and not tied to a single entity.
    """

    __tablename__ = "ai_run_logs"
    __table_args__ = (
        Index("ai_run_logs_kind_idx", "kind", "created_at"),
        Index("ai_run_logs_user_idx", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[AIRunKind] = mapped_column(
        SAEnum(AIRunKind, name="ai_run_kind", native_enum=True),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Indexed flag so dashboards can quickly count failures over a window.
    success: Mapped[bool] = mapped_column(nullable=False, default=True)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class LinkSuggestionStatus(str, Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"
    # Marked when the underlying ports change or a manual link is created
    # between them outside the suggestion flow.
    superseded = "superseded"


class LinkSuggestion(Base):
    """A candidate Link surfaced by the AI suggest-links scan.

    Stored canonical (port_a_id < port_b_id) just like `Link`, so we can
    cheaply detect overlap with the real `links` table. `accepted_link_id`
    is set when the suggestion graduates into a real link — keeping the
    pointer lets the UI show "you accepted this AI suggestion 3 days ago".
    """

    __tablename__ = "link_suggestions"
    __table_args__ = (
        CheckConstraint("port_a_id <> port_b_id", name="link_suggestions_distinct_ports"),
        CheckConstraint("port_a_id < port_b_id", name="link_suggestions_canonical_order"),
        # Only one pending suggestion per port pair — a re-scan that surfaces
        # the same pair updates the existing row instead of duplicating.
        UniqueConstraint(
            "port_a_id", "port_b_id", "status", name="link_suggestions_pair_status_uniq"
        ),
        Index("link_suggestions_status_idx", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_run_logs.id", ondelete="SET NULL")
    )
    port_a_id: Mapped[int] = mapped_column(
        ForeignKey("ports.id", ondelete="CASCADE"),
        nullable=False,
    )
    port_b_id: Mapped[int] = mapped_column(
        ForeignKey("ports.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Optional link-type guess. Falls back to "copper" if the AI didn't say.
    link_type: Mapped[str] = mapped_column(String(16), nullable=False, default="copper")
    # Bounded 0.0–1.0; we clamp on insert.
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[LinkSuggestionStatus] = mapped_column(
        SAEnum(LinkSuggestionStatus, name="link_suggestion_status", native_enum=True),
        nullable=False,
        default=LinkSuggestionStatus.pending,
    )
    accepted_link_id: Mapped[int | None] = mapped_column(
        ForeignKey("links.id", ondelete="SET NULL")
    )
    resolved_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
