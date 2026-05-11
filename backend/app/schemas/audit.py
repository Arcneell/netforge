"""Audit log read schemas — write-side is handled by the SQLAlchemy listeners."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict


class AuditAction(str, Enum):
    create = "create"
    update = "update"
    delete = "delete"


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None
    action: AuditAction
    entity: str
    entity_id: int | None
    changes: dict | None
    ip_address: str | None
    user_agent: str | None
    created_at: datetime
