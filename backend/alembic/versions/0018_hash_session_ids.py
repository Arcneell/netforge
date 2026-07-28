"""hash session ids at rest

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-28

`sessions.id` used to store the raw cookie token as the primary key —
anyone with read access to the table (DB dump, over-broad grant, backup
leak) could replay a row's PK as a valid login cookie. The application now
stores only the SHA-256 hex digest of the token (64 chars, same String(64)
column — no schema change), mirroring how `api_tokens.token_hash` already
works.

Existing rows are NOT hashed in place: doing it in SQL needs pgcrypto's
`digest()`, and no prior migration enables pgcrypto — CREATE EXTENSION
requires superuser on several managed Postgres offerings, so introducing
that dependency for a one-shot backfill isn't worth it. We DELETE the rows
instead: every active session is invalidated once and users simply
re-authenticate through their IdP. Sessions are short-lived (8h sliding)
so the blast radius is one forced re-login.

Downgrade also deletes: the digests cannot be reversed into cookie values,
so rows written by the new code are unusable by the old code anyway.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Invalidate every stored session — the application now looks rows up
    # by sha256(cookie), so plaintext-keyed rows would never match again
    # and would only sit in the table until the expiry purge.
    op.execute("DELETE FROM sessions")


def downgrade() -> None:
    # Irreversible: hashed ids have no recoverable cookie value. Deleting
    # forces a clean re-login on the downgraded version too.
    op.execute("DELETE FROM sessions")
