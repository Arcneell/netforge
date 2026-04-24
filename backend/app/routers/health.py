"""Healthcheck endpoint — verifies the app is up and the DB answers."""

import time

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session

router = APIRouter(tags=["health"])

_STARTED_AT = time.monotonic()


@router.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict:
    """Healthcheck consumed by Docker, Zabbix, etc.

    Returns `{ status, db, uptime_s }`. If the DB is unreachable the endpoint
    still returns 200 with `db: "down"` so that clients can distinguish
    app-down from db-down — this matches the behaviour described in docs/07.
    """
    uptime = int(time.monotonic() - _STARTED_AT)

    db_status = "ok"
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        db_status = "down"

    return {
        "status": "ok",
        "db": db_status,
        "uptime_s": uptime,
    }
