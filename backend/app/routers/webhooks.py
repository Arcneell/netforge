"""Outbound webhooks router — /api/webhooks (admin-only).

Admins manage subscribers (URL + event patterns) here. Plaintext secrets
are visible only in the create / rotate-secret responses; the list / get
endpoints never return them.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.db import get_session as get_db
from app.models.user import UserRole
from app.models.webhook import Webhook, WebhookDelivery
from app.schemas.webhook import (
    WebhookCreate,
    WebhookCreated,
    WebhookDeliveryRead,
    WebhookRead,
    WebhookUpdate,
)
from app.services.errors import catch_integrity_errors, not_found
from app.services.webhooks import (
    generate_secret,
    refresh_dispatch_enabled,
    send_test_event,
)

router = APIRouter(
    prefix="/webhooks",
    tags=["webhooks"],
    dependencies=[Depends(require_role(UserRole.admin))],
)


@router.get("", response_model=list[WebhookRead])
async def list_webhooks(db: AsyncSession = Depends(get_db)) -> list[WebhookRead]:
    result = await db.execute(select(Webhook).order_by(Webhook.id.asc()))
    return [WebhookRead.model_validate(w) for w in result.scalars().all()]


@router.post("", response_model=WebhookCreated, status_code=status.HTTP_201_CREATED)
async def create_webhook(
    payload: WebhookCreate, db: AsyncSession = Depends(get_db)
) -> WebhookCreated:
    secret = generate_secret()
    row = Webhook(
        name=payload.name,
        url=str(payload.url),
        secret=secret,
        events=payload.events,
        enabled=payload.enabled,
    )
    with catch_integrity_errors():
        db.add(row)
        await db.commit()
    await db.refresh(row)
    await refresh_dispatch_enabled()
    return WebhookCreated(secret=secret, **WebhookRead.model_validate(row).model_dump())


@router.get("/{webhook_id}", response_model=WebhookRead)
async def get_webhook(
    webhook_id: int, db: AsyncSession = Depends(get_db)
) -> WebhookRead:
    row = await db.get(Webhook, webhook_id)
    if row is None:
        not_found("Webhook", webhook_id)
    return WebhookRead.model_validate(row)


@router.patch("/{webhook_id}", response_model=WebhookRead)
async def update_webhook(
    webhook_id: int,
    payload: WebhookUpdate,
    db: AsyncSession = Depends(get_db),
) -> WebhookRead:
    row = await db.get(Webhook, webhook_id)
    if row is None:
        not_found("Webhook", webhook_id)
    data = payload.model_dump(exclude_unset=True)
    if "url" in data and data["url"] is not None:
        data["url"] = str(data["url"])
    for k, v in data.items():
        setattr(row, k, v)
    with catch_integrity_errors():
        await db.commit()
    await db.refresh(row)
    await refresh_dispatch_enabled()
    return WebhookRead.model_validate(row)


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    webhook_id: int, db: AsyncSession = Depends(get_db)
) -> None:
    row = await db.get(Webhook, webhook_id)
    if row is None:
        not_found("Webhook", webhook_id)
    await db.delete(row)
    await db.commit()
    await refresh_dispatch_enabled()


@router.post("/{webhook_id}/rotate-secret", response_model=WebhookCreated)
async def rotate_secret(
    webhook_id: int, db: AsyncSession = Depends(get_db)
) -> WebhookCreated:
    row = await db.get(Webhook, webhook_id)
    if row is None:
        not_found("Webhook", webhook_id)
    new_secret = generate_secret()
    row.secret = new_secret
    await db.commit()
    await db.refresh(row)
    return WebhookCreated(
        secret=new_secret, **WebhookRead.model_validate(row).model_dump()
    )


@router.post("/{webhook_id}/test", response_model=WebhookDeliveryRead)
async def test_webhook(
    webhook_id: int, db: AsyncSession = Depends(get_db)
) -> WebhookDeliveryRead:
    row = await db.get(Webhook, webhook_id)
    if row is None:
        not_found("Webhook", webhook_id)
    delivery = await send_test_event(row)
    return WebhookDeliveryRead.model_validate(delivery)


@router.get(
    "/{webhook_id}/deliveries", response_model=list[WebhookDeliveryRead]
)
async def list_deliveries(
    webhook_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[WebhookDeliveryRead]:
    row = await db.get(Webhook, webhook_id)
    if row is None:
        not_found("Webhook", webhook_id)
    result = await db.execute(
        select(WebhookDelivery)
        .where(WebhookDelivery.webhook_id == webhook_id)
        .order_by(WebhookDelivery.id.desc())
        .limit(limit)
    )
    return [WebhookDeliveryRead.model_validate(d) for d in result.scalars().all()]
