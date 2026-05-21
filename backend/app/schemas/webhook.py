"""Webhook subscription + delivery schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

# Mirror the entity names used by the audit listener (see `services/audit.py`).
# Wildcards: "*" for all events, "{entity}.*" for all actions on an entity.
_ENTITIES = {
    "site", "room", "vlan", "subnet", "ip",
    "device", "switch", "port", "link",
}
_ACTIONS = {"create", "update", "delete"}


def _validate_pattern(p: str) -> str:
    p = p.strip().lower()
    if p == "*":
        return p
    if "." not in p:
        raise ValueError(f"event pattern '{p}' must be '*' or '{{entity}}.{{action|*}}'")
    entity, action = p.split(".", 1)
    if entity not in _ENTITIES:
        raise ValueError(f"unknown entity '{entity}' in pattern '{p}'")
    if action != "*" and action not in _ACTIONS:
        raise ValueError(f"unknown action '{action}' in pattern '{p}'")
    return p


class WebhookCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    url: HttpUrl
    events: list[str] = Field(default_factory=lambda: ["*"], min_length=1)
    enabled: bool = True

    @field_validator("events")
    @classmethod
    def _normalize(cls, v: list[str]) -> list[str]:
        return [_validate_pattern(p) for p in v]


class WebhookUpdate(BaseModel):
    """All fields optional — PATCH semantics."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    url: HttpUrl | None = None
    events: list[str] | None = Field(default=None, min_length=1)
    enabled: bool | None = None

    @field_validator("events")
    @classmethod
    def _normalize(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        return [_validate_pattern(p) for p in v]


class WebhookRead(BaseModel):
    """Public metadata — never includes the secret."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    url: str
    events: list[str]
    enabled: bool
    total_deliveries: int
    total_failures: int
    last_delivery_at: datetime | None
    last_status_code: int | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class WebhookCreated(WebhookRead):
    """Returned by POST + rotate-secret — includes the plaintext secret
    exactly once. Operators must copy it immediately; we cannot recover it."""

    secret: str


class WebhookDeliveryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    webhook_id: int
    event: str
    status_code: int
    success: bool
    error: str | None
    latency_ms: int
    created_at: datetime
