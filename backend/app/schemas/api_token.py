"""API tokens — request / response schemas.

The plaintext token is part of the *create* response only (`ApiTokenCreated`)
and is shown once to the user. Subsequent reads only return metadata.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.user import ApiTokenScope


class ApiTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    # Optional explicit expiry; if omitted the token never expires (admins
    # can still revoke it manually).
    expires_at: datetime | None = None
    # `full` (default) inherits the caller's role, same as before this field
    # existed. `read_only` caps the token to viewer-level reads regardless of
    # the caller's actual role — see `app.models.user.ApiTokenScope`. Being a
    # strict enum, an unrecognised value is rejected with a 422 rather than
    # silently falling back to `full`.
    scope: ApiTokenScope = ApiTokenScope.full


class ApiTokenRead(BaseModel):
    """Metadata only — the plaintext is never re-exposed after creation."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    name: str
    prefix: str
    scope: ApiTokenScope
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiTokenCreated(ApiTokenRead):
    """Returned by POST — includes the plaintext exactly once. Do not store
    or log this value; the client is expected to copy it immediately."""

    token: str
