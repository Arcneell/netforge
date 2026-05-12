"""CSV import — POST /api/imports/{entity}, /detect, /bulk."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.db import get_session as get_db
from app.models.user import UserRole
from app.schemas.imports import BulkImportReport, DetectReport, ImportReport
from app.services import csv_import as service
from app.services.errors import business_rule

router = APIRouter(prefix="/imports", tags=["imports"])

_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB hard cap, per single CSV


def _enforce_size(content: bytes) -> None:
    if len(content) > _MAX_BYTES:
        business_rule(
            "CSV_TOO_LARGE",
            f"Upload exceeds the {_MAX_BYTES} byte limit.",
            details={"size": len(content), "max": _MAX_BYTES},
        )


# Detect must be declared BEFORE the catch-all `/{entity}` route, otherwise
# "detect" would be interpreted as an entity name and 400 on UNKNOWN_ENTITY.
@router.post(
    "/detect",
    response_model=DetectReport,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def detect_csv(file: UploadFile = File(...)) -> DetectReport:
    """Inspect a CSV's header row and guess which entity it belongs to."""
    content = await file.read()
    _enforce_size(content)
    return service.detect_entity(content)


@router.post(
    "/bulk",
    response_model=BulkImportReport,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def import_bulk(
    files: list[UploadFile] = File(...),
    dry_run: bool = Form(default=False),
    db: AsyncSession = Depends(get_db),
) -> BulkImportReport:
    """Import many CSVs at once (or a single ZIP of CSVs).

    Each file is auto-routed to the matching entity importer based on its
    header row. Files run in dependency order, inside one transaction; any
    failure rolls the whole batch back. `dry_run=true` always rolls back.
    """
    payloads: list[tuple[str, bytes]] = []
    for f in files:
        content = await f.read()
        name = f.filename or "upload.csv"
        # A single .zip member explodes into its CSVs in-place; mixing a zip
        # with extra loose CSVs in the same request is supported too.
        if name.lower().endswith(".zip"):
            payloads.extend(service.extract_zip(content))
        else:
            payloads.append((name, content))

    total = sum(len(c) for _, c in payloads)
    if total > service.BULK_MAX_TOTAL_BYTES:
        business_rule(
            "BULK_TOO_LARGE",
            f"Total upload exceeds the {service.BULK_MAX_TOTAL_BYTES} byte limit.",
            details={"size": total, "max": service.BULK_MAX_TOTAL_BYTES},
        )

    return await service.run_bulk_import(db, payloads, dry_run=dry_run)


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
    _enforce_size(content)
    return await service.run_import(db, entity, content, dry_run=dry_run)
