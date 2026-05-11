"""CSV import — POST /api/imports/{entity}."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.db import get_session as get_db
from app.models.user import UserRole
from app.schemas.imports import ImportReport
from app.services import csv_import as service

router = APIRouter(prefix="/imports", tags=["imports"])

_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB hard cap


@router.post(
    "/{entity}",
    response_model=ImportReport,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def import_entity(
    entity: str,
    file: UploadFile = File(...),
    dry_run: bool = Form(default=False),
    db: AsyncSession = Depends(get_db),
) -> ImportReport:
    content = await file.read()
    if len(content) > _MAX_BYTES:
        from app.services.errors import business_rule

        business_rule(
            "CSV_TOO_LARGE",
            f"Upload exceeds the {_MAX_BYTES} byte limit.",
            details={"size": len(content), "max": _MAX_BYTES},
        )
    return await service.run_import(db, entity, content, dry_run=dry_run)
