"""ai_run_logs + link_suggestions — AI integration scaffolding.

Revision ID: 0003_ai_tables
Revises: 0002_api_tokens
Create Date: 2026-05-18

Adds two tables:
- `ai_run_logs` records every call to an AI provider (kind, provider, model,
  token counts, latency, success). Lives separately from `audit_log` because
  AI calls are cross-cutting (not tied to a single entity row).
- `link_suggestions` stores topology link candidates surfaced by the AI
  suggest-links scan. Canonical pair order (port_a_id < port_b_id) mirrors
  the real `links` table so we can cheaply diff. `accepted_link_id` ties
  back to the created link once a suggestion is approved.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_ai_tables"
down_revision: str | None = "0002_api_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    ai_run_kind = sa.Enum(
        "suggest_links",
        "advisor",
        "nl_query",
        name="ai_run_kind",
        native_enum=True,
    )
    ai_run_kind.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "ai_run_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("kind", ai_run_kind, nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("error", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ai_run_logs_kind_idx", "ai_run_logs", ["kind", "created_at"])
    op.create_index("ai_run_logs_user_idx", "ai_run_logs", ["user_id", "created_at"])

    link_suggestion_status = sa.Enum(
        "pending",
        "accepted",
        "rejected",
        "superseded",
        name="link_suggestion_status",
        native_enum=True,
    )
    link_suggestion_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "link_suggestions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("ai_run_logs.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "port_a_id",
            sa.Integer(),
            sa.ForeignKey("ports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "port_b_id",
            sa.Integer(),
            sa.ForeignKey("ports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("link_type", sa.String(16), nullable=False, server_default="copper"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("reasoning", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", link_suggestion_status, nullable=False, server_default="pending"),
        sa.Column(
            "accepted_link_id",
            sa.Integer(),
            sa.ForeignKey("links.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "resolved_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("port_a_id <> port_b_id", name="link_suggestions_distinct_ports"),
        sa.CheckConstraint("port_a_id < port_b_id", name="link_suggestions_canonical_order"),
        sa.UniqueConstraint(
            "port_a_id", "port_b_id", "status", name="link_suggestions_pair_status_uniq"
        ),
    )
    op.create_index(
        "link_suggestions_status_idx",
        "link_suggestions",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("link_suggestions_status_idx", table_name="link_suggestions")
    op.drop_table("link_suggestions")
    sa.Enum(name="link_suggestion_status").drop(op.get_bind(), checkfirst=True)

    op.drop_index("ai_run_logs_user_idx", table_name="ai_run_logs")
    op.drop_index("ai_run_logs_kind_idx", table_name="ai_run_logs")
    op.drop_table("ai_run_logs")
    sa.Enum(name="ai_run_kind").drop(op.get_bind(), checkfirst=True)
