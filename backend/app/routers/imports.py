"""CSV import — POST /api/imports/{entity}, /detect, /bulk."""

from __future__ import annotations

import json

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
_READ_CHUNK = 64 * 1024  # 64 KiB chunks for the streaming read


def _enforce_size(content: bytes) -> None:
    """Belt-and-suspenders length check for callers that already have
    bytes in memory (legacy code paths, tests). The route entry points
    use `_read_capped` so the bytes never exceed `_MAX_BYTES` to begin
    with — but if a caller hands us a literal `bytes` larger than the
    cap, refuse here too.
    """
    if len(content) > _MAX_BYTES:
        business_rule(
            "CSV_TOO_LARGE",
            f"Upload exceeds the {_MAX_BYTES} byte limit.",
            details={"size": len(content), "max": _MAX_BYTES},
        )


async def _read_capped(file: UploadFile, *, max_bytes: int = _MAX_BYTES) -> bytes:
    """Stream the upload into memory, enforcing `max_bytes` as we go.

    The previous `await file.read()` materialised the whole body before
    the size check — nginx's 16 MiB body cap meant an admin (or an
    admin API token holder) could force ~16 MiB of resident memory per
    concurrent request before the 10 MiB refusal fired. Stream-reading
    in 64 KiB chunks bounds the peak at `max_bytes` and refuses early.

    The cap is parameterised because the bulk endpoint accepts a single
    ZIP of CSVs whose compressed size can legitimately exceed the
    per-CSV cap. The single-CSV routes still pass the default
    `_MAX_BYTES`; the bulk route raises the cap to
    `BULK_MAX_TOTAL_BYTES` for ZIP members and to `_MAX_BYTES` for
    loose CSVs.
    """
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = await file.read(_READ_CHUNK)
        if not chunk:
            break
        size += len(chunk)
        if size > max_bytes:
            business_rule(
                "CSV_TOO_LARGE",
                f"Upload exceeds the {max_bytes} byte limit.",
                details={"size": size, "max": max_bytes},
            )
        chunks.append(chunk)
    return b"".join(chunks)


# Detect must be declared BEFORE the catch-all `/{entity}` route, otherwise
# "detect" would be interpreted as an entity name and 400 on UNKNOWN_ENTITY.
@router.post(
    "/detect",
    response_model=DetectReport,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def detect_csv(file: UploadFile = File(...)) -> DetectReport:
    """Inspect a CSV's header row and guess which entity it belongs to."""
    content = await _read_capped(file)
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
        name = f.filename or "upload.csv"
        # ZIP members are bounded by BULK_MAX_TOTAL_BYTES (50 MiB) on
        # the compressed side and by ZIP_MAX_UNCOMPRESSED inside
        # extract_zip — applying the 10 MiB single-CSV cap here would
        # reject perfectly valid /exports/all round-trips whose
        # compressed ZIP happens to fall between 10 MiB and 50 MiB.
        # Loose CSVs in a bulk submit are still capped at _MAX_BYTES
        # each so a single bogus file can't OOM the worker.
        if name.lower().endswith(".zip"):
            content = await _read_capped(f, max_bytes=service.BULK_MAX_TOTAL_BYTES)
            payloads.extend(service.extract_zip(content))
        else:
            content = await _read_capped(f)
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
    column_map: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
) -> ImportReport:
    """Import one CSV. The optional `column_map` is a JSON dict
    `{csv_column: netforge_field | null}` — when present the header row is
    rewritten in-memory before parsing. This is what backs the AI mapping
    assistant: the operator pastes their CSV, the LLM proposes the mapping,
    and the import is replayed with that mapping applied automatically."""
    content = await _read_capped(file)
    parsed_map: dict[str, str | None] | None = None
    if column_map:
        try:
            raw = json.loads(column_map)
        except json.JSONDecodeError:
            business_rule(
                "BAD_COLUMN_MAP",
                "`column_map` must be valid JSON.",
            )
        if not isinstance(raw, dict):
            business_rule(
                "BAD_COLUMN_MAP",
                "`column_map` must be a JSON object of {csv_column: field}.",
            )
        # Normalise values: anything other than a non-empty string becomes
        # `None` (= drop column). Keeps the downstream service simple.
        parsed_map = {
            str(k): (str(v) if isinstance(v, str) and v.strip() else None)
            for k, v in raw.items()
        }
    return await service.run_import(
        db, entity, content, dry_run=dry_run, column_map=parsed_map
    )
