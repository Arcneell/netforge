"""api_tokens — personal access tokens for programmatic API access.

Revision ID: 0002_api_tokens
Revises: 0001_initial
Create Date: 2026-05-13

Adds the `api_tokens` table. The plaintext token is shown once at creation
and never stored — only its SHA-256 digest (`token_hash`) lives in the DB,
so a database leak can't be replayed against the API. `prefix` keeps the
first few chars in clear so admins can recognise a token in the management
UI without exposing the secret.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_api_tokens"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("token_hash", name="api_tokens_hash_uniq"),
    )
    op.create_index("api_tokens_user_idx", "api_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_index("api_tokens_user_idx", table_name="api_tokens")
    op.drop_table("api_tokens")
