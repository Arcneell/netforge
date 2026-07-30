"""api_tokens.scope — cap a leaked read-only token to viewer privileges

Revision ID: 0023
Revises: 0022
Create Date: 2026-07-29

Audit finding: a personal access token inherits its owner's role verbatim,
admin included. A "read-only" CI token that leaks today is therefore
equivalent to leaking a full admin session — there was no way to mint a
token that couldn't write.

This adds `api_tokens.scope`, a native enum (`full` | `read_only`,
`server_default 'full'` so every existing token keeps behaving exactly as
before). Enforcement is entirely application-side, in
`app/auth/dependencies.py::get_current_user`: a request authenticated by a
`read_only` token gets its effective role capped to `viewer` for that
request only — the column itself carries no DB-level behaviour, it is just
data `verify_token` reads back.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENUM_NAME = "api_token_scope"


def upgrade() -> None:
    # `create_type=False` on the column-side reference: we own the enum's
    # lifecycle explicitly via .create()/.drop() with checkfirst=True, same
    # pattern as `ai_run_kind` / `link_suggestion_status` in 0003_ai_tables —
    # letting `op.add_column` issue its own CREATE TYPE would error on a
    # re-run that recovered from a partial previous failure.
    scope = postgresql.ENUM("full", "read_only", name=_ENUM_NAME, create_type=False)
    scope.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "api_tokens",
        sa.Column("scope", scope, nullable=False, server_default="full"),
    )


def downgrade() -> None:
    op.drop_column("api_tokens", "scope")
    postgresql.ENUM(name=_ENUM_NAME, create_type=False).drop(
        op.get_bind(), checkfirst=True
    )
