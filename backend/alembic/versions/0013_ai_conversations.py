"""add ai_conversations + ai_conversation_turns

Revision ID: 0013_ai_conversations
Revises: 0012_ipam_indexes
Create Date: 2026-05-27

Adds persistent storage for Ask-AI conversation threads. Each
`ai_conversations` row groups N `ai_conversation_turns` (one per
user prompt / AI reply). Turns store the rendered text plus the
JSONB entity list the AI cited so re-rendering the chat doesn't
need a fresh LLM call.

Privacy: both tables CASCADE on `users.id` so account deletion wipes
the entire chat history.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0013_ai_conversations"
down_revision: str | None = "0012_ipam_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ai_conversations_user_idx",
        "ai_conversations",
        ["user_id", "updated_at"],
    )

    op.create_table(
        "ai_conversation_turns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            sa.ForeignKey("ai_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("entities", JSONB(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "role IN ('user', 'assistant')",
            name="ai_conversation_turns_role_check",
        ),
    )
    op.create_index(
        "ai_conversation_turns_conv_idx",
        "ai_conversation_turns",
        ["conversation_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ai_conversation_turns_conv_idx", table_name="ai_conversation_turns")
    op.drop_table("ai_conversation_turns")
    op.drop_index("ai_conversations_user_idx", table_name="ai_conversations")
    op.drop_table("ai_conversations")
