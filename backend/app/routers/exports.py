"""CSV export — GET /api/exports/{entity}, /all."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db import get_session as get_db
from app.services import csv_export as service
from app.services.errors import http_error

router = APIRouter(prefix="/exports", tags=["exports"])


# `/all` must be declared BEFORE the catch-all `/{entity}` below, otherwise
# FastAPI would route "all" as an entity name and 400 on UNKNOWN_ENTITY.
@router.get("/all", dependencies=[Depends(get_current_user)])
async def export_all(db: AsyncSession = Depends(get_db)) -> Response:
    """Bundle every entity's CSV into a single ZIP archive.

    The archive is structured exactly like what `POST /api/imports/bulk`
    accepts (one `<entity>.csv` per member, headers matching the importer),
    so it doubles as a logical backup and as a round-trip-ready snapshot.
    """
    payload = await service.build_zip(db)
    filename = f"netforge-export-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.zip"
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
