"""add error_code to ai_action_drafts

Revision ID: 0014_ai_draft_error_code
Revises: 0013_ai_conversations
Create Date: 2026-05-28

Persists the stable UPPER_SNAKE error code alongside `error_message` on
failed drafts. The frontend uses the code to look up a localized string
in its i18n bundle so the failed-draft card reads "Ce CIDR chevauche un
sous-réseau existant" instead of the raw asyncpg dump.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_ai_draft_error_code"
down_revision: str | None = "0013_ai_conversations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_action_drafts",
        sa.Column("error_code", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_action_drafts", "error_code")
