"""CSV export — GET /api/exports/{entity}."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db import get_session as get_db
from app.services import csv_export as service
from app.services.errors import http_error

router = APIRouter(prefix="/exports", tags=["exports"])


@router.get("/{entity}", dependencies=[Depends(get_current_user)])
async def export_entity(
    entity: str, db: AsyncSession = Depends(get_db)
) -> StreamingResponse:
    if entity not in service.ENTITIES:
        http_error(
            400,
            "UNKNOWN_ENTITY",
            f"Unknown entity {entity!r}. Expected one of: {list(service.ENTITIES)}.",
        )
    filename = f"netforge-{entity}.csv"
    return StreamingResponse(
        service.stream_export(db, entity),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
