"""ai_action_drafts — NL-to-action drafts pending operator approval.

Revision ID: 0006_ai_action_drafts
Revises: 0005_ai_schedules
Create Date: 2026-05-19

Each row is an AI-proposed CRUD action (create a VLAN, a subnet, …) that
an admin has to explicitly apply. The system never executes a draft on
its own — applying is always a deliberate POST from the UI.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_ai_action_drafts"
down_revision: str | None = "0005_ai_schedules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    status = postgresql.ENUM(
        "pending",
        "applied",
        "rejected",
        "failed",
        name="ai_action_draft_status",
        create_type=False,
    )
    status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "ai_action_drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(50), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column(
            "status",
            status,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        # Free-form pointer to whatever entity got created on apply
        # ("vlan:42", "subnet:7"). Kept as text to avoid coupling to any
        # single FK table; the UI just renders it as a chip.
        sa.Column("applied_resource", sa.String(120), nullable=True),
        sa.Column(
            "applied_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ai_action_drafts_status_idx",
        "ai_action_drafts",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ai_action_drafts_status_idx", table_name="ai_action_drafts")
    op.drop_table("ai_action_drafts")
    postgresql.ENUM(name="ai_action_draft_status", create_type=False).drop(
        op.get_bind(), checkfirst=True
    )
