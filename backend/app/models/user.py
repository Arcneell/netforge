"""Users, sessions and audit log."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UserRole(str, Enum):
    viewer = "viewer"
    admin = "admin"


class AuditAction(str, Enum):
    create = "create"
    update = "update"
    delete = "delete"


class ApiTokenScope(str, Enum):
    """How much of the owner's role a token is allowed to exercise.

    ``full`` (the historical, still-default behaviour) inherits the owner's
    role verbatim — an admin's token can do anything the admin can.
    ``read_only`` caps the token to `UserRole.viewer` for the lifetime of the
    request it authenticates, regardless of the owner's real role: a leaked
    CI token minted as ``read_only`` can list/get, never write. Enforcement
    lives in `app/auth/dependencies.py::get_current_user`, not here — this
    column is only ever read, never interpreted by the DB.
    """

    full = "full"
    read_only = "read_only"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("provider", "subject", name="users_provider_subject_uniq"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Provider key — short stable identifier ("github", "oidc", ...).
    # Pluggable: see app/auth/factory.py.
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    # Subject as returned by the provider — opaque string.
    # GitHub: numeric user.id rendered as string. OIDC: the `sub` claim.
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role", native_enum=True),
        nullable=False,
        default=UserRole.viewer,
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Session(Base):
    """DB-backed sessions (see docs/06-auth.md)."""

    __tablename__ = "sessions"

    # SHA-256 hex digest (64 chars) of the opaque cookie token — the raw
    # token is never persisted (see app/auth/sessions.py).
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)


class ApiToken(Base):
    """Personal access tokens for programmatic API access (scripts, CI).

    Storage rules:
      - The plaintext token is shown **once** at creation and never persisted.
      - We store only its SHA-256 digest (`token_hash`) — same trick as GitHub
        PATs. Lookup is O(1) since we index on the hash.
      - `prefix` keeps the first ~8 chars of the plaintext in clear so admins
        can identify a token in the list without revealing it.
      - `revoked_at` is the soft-delete: an active token has `revoked_at = NULL`
        AND (`expires_at` IS NULL OR `expires_at > now()`).

    A token inherits its owner's role by default (`scope="full"`): revoking
    the user's access (or demoting them to viewer) instantly limits what the
    token can do. `scope="read_only"` caps it further, to viewer-level reads
    only, independent of the owner's actual role — see `ApiTokenScope`.
    """

    __tablename__ = "api_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="api_tokens_hash_uniq"),
        Index("api_tokens_user_idx", "user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # First few chars of the plaintext, kept so admins can recognise a token
    # in the list ("nfp_abcd…") without re-displaying the secret.
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    scope: Mapped[ApiTokenScope] = mapped_column(
        SAEnum(ApiTokenScope, name="api_token_scope", native_enum=True, create_type=False),
        nullable=False,
        default=ApiTokenScope.full,
        server_default=ApiTokenScope.full.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("audit_log_entity_idx", "entity", "entity_id"),
        Index("audit_log_user_idx", "user_id"),
        Index("audit_log_created_at_idx", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[AuditAction] = mapped_column(
        SAEnum(AuditAction, name="audit_action", native_enum=True),
        nullable=False,
    )
    entity: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[int | None] = mapped_column()
    changes: Mapped[dict | None] = mapped_column(JSONB)
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
