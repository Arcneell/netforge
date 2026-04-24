"""Endpoint de healthcheck — vérifie que l'app tourne et que la DB répond."""

import time

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session

router = APIRouter(tags=["health"])

_STARTED_AT = time.monotonic()


@router.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict:
    """Healthcheck. Consommé par Docker, Zabbix, etc.

    Retourne `{ status, db, uptime_s }`. Si la DB est indisponible, renvoie
    quand même 200 avec `db: "down"` pour permettre au client de différencier
    app-down vs db-down — c'est le comportement attendu dans docs/07.
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
