"""Driver — parse, validate, apply, commit.

Owns the transaction boundary and the reference-cache scope: one cache per
`run_import` / `run_bulk_import` call, i.e. exactly one per transaction, torn
down on the commit *and* on both rollback paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.schemas.imports import (
    BulkImportFileReport,
    BulkImportReport,
    DetectReport,
    ImportErrorRow,
    ImportReport,
)
from app.services.csv_import.detect import detect_entity
from app.services.csv_import.errors import (
    _format_validation_errors,
    _friendly_integrity,
    _RefError,
)
from app.services.csv_import.parsing import (
    BULK_MAX_FILES,
    BULK_MAX_TOTAL_BYTES,
    TOO_MANY_COLUMNS_KEY,
    _parse_csv,
    _rows_with_invalid_encoding,
    apply_column_mapping,
)
from app.services.csv_import.persist import IMPORT_ORDER, SPECS, _ImportSpec
from app.services.csv_import.refs import _ref_cache_scope


@dataclass
class _SingleResult:
    """Outcome of importing one CSV without commit/rollback. The caller is
    responsible for committing the surrounding transaction."""

    parsed_rows: int
    ok_rows: int
    error_rows: list[ImportErrorRow]
    warnings: list[str] = field(default_factory=list)


class _NeedsSavepointRetry(Exception):
    """Internal signal only — never escapes `_import_one`.

    Raised when the fast apply pass (see `_run_apply_pass`) hits an
    `IntegrityError` without a SAVEPOINT in place. PostgreSQL aborts the
    whole transaction on that error, so nothing else in it can run until a
    ROLLBACK — including any later row in this same file. Wrapping the fast
    pass in `begin_nested()` lets us roll back to a SAVEPOINT instead of the
    whole (possibly multi-file, see `run_bulk_import`) transaction, then
    retry the file with a SAVEPOINT around every row.
    """


async def _run_apply_pass(
    db: AsyncSession,
    parsed: list[tuple[int, BaseModel, dict[str, str]]],
    spec: _ImportSpec,
    *,
    use_savepoints: bool,
) -> tuple[int, list[ImportErrorRow]]:
    """One pass over `parsed`, persisting + flushing each row.

    `_RefError` / `HTTPException` are pure validation failures — nothing they
    do reaches the database in a way that can abort the transaction, so the
    loop always keeps going past them, `use_savepoints` or not.

    `IntegrityError` is different: it comes from a real `flush()`, and
    PostgreSQL poisons the whole transaction once one fires. With
    `use_savepoints=False` this pass stops there and raises
    `_NeedsSavepointRetry` — the caller must roll back (to the SAVEPOINT it
    wrapped this call in) and retry with `use_savepoints=True`, which puts
    every row in its own SAVEPOINT so a later row's constraint violation
    can't cascade into the ones after it.
    """
    apply_errors: list[ImportErrorRow] = []
    success_count = 0
    for line, model, _raw in parsed:
        try:
            if use_savepoints:
                async with db.begin_nested():
                    await spec.persist(db, model)
                    await db.flush()
            else:
                await spec.persist(db, model)
                await db.flush()
        except _RefError as e:
            apply_errors.append(
                ImportErrorRow(
                    line=line, column=e.column, value=e.value, error=e.message
                )
            )
            continue
        except IntegrityError as e:
            apply_errors.append(
                ImportErrorRow(
                    line=line, error=_friendly_integrity(str(getattr(e, "orig", e)))
                )
            )
            if not use_savepoints:
                raise _NeedsSavepointRetry from e
            continue
        except HTTPException as e:
            err_obj: dict[str, Any] = (
                e.detail.get("error", {}) if isinstance(e.detail, dict) else {}
            )
            apply_errors.append(
                ImportErrorRow(
                    line=line,
                    error=str(err_obj.get("message") or err_obj.get("code") or e.detail),
                )
            )
            continue
        success_count += 1

    return success_count, apply_errors


async def _import_one(
    db: AsyncSession, entity: str, content: bytes
) -> _SingleResult:
    """Parse + validate + flush all rows of one CSV against `db`.

    Does NOT commit or rollback — that's the caller's job. This lets the bulk
    importer chain several CSVs in a single transaction and roll the whole
    thing back if any file fails.
    """
    if entity not in SPECS:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "UNKNOWN_ENTITY",
                    "message": f"Unknown entity {entity!r}. "
                    f"Expected one of: {sorted(SPECS)}.",
                }
            },
        )
    spec = SPECS[entity]

    rows = _parse_csv(content)
    if not rows:
        return _SingleResult(parsed_rows=0, ok_rows=0, error_rows=[])

    max_rows = get_settings().csv_import_max_rows
    if len(rows) > max_rows:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "TOO_MANY_ROWS",
                    "message": (
                        f"CSV has {len(rows)} data rows, exceeding the "
                        f"{max_rows} row limit. Split the file into smaller "
                        "batches or raise CSV_IMPORT_MAX_ROWS."
                    ),
                }
            },
        )

    # Silent-corruption guard: `_parse_csv` decodes with `errors="replace"`
    # so one bad byte can't 500 the whole import, but that must not mean the
    # operator never finds out a value was mangled.
    warnings = [
        f"line {i + 2}: row contains the Unicode replacement character "
        "(U+FFFD) — the source file may not be valid UTF-8; check for "
        "corrupted values in this row."
        for i in _rows_with_invalid_encoding(rows)
    ]

    # ---- Parse / validate phase ------------------------------------------
    parsed: list[tuple[int, BaseModel, dict[str, str]]] = []
    parse_errors: list[ImportErrorRow] = []
    for i, raw in enumerate(rows, start=2):  # row 1 = header
        if TOO_MANY_COLUMNS_KEY in raw:
            parse_errors.append(
                ImportErrorRow(
                    line=i,
                    error="Row has more columns than the header row.",
                )
            )
            continue
        try:
            model = spec.row_model.model_validate(raw)
        except ValidationError as exc:
            parse_errors.extend(_format_validation_errors(i, raw, exc))
            continue
        parsed.append((i, model, raw))

    if parse_errors:
        return _SingleResult(
            parsed_rows=len(rows),
            ok_rows=0,
            error_rows=parse_errors,
            warnings=warnings,
        )

    # ---- Apply phase -------------------------------------------------
    # Fast path first, no SAVEPOINT overhead: `_RefError`/`HTTPException`
    # already get collected in full for free (see `_run_apply_pass`), which
    # covers the common case (a row references something that doesn't
    # exist). The whole pass runs inside ONE SAVEPOINT so that, if a row
    # hits a genuine `IntegrityError`, we can roll back just THIS file's
    # work (not the other files already flushed in the same transaction —
    # `run_bulk_import` shares one transaction across the whole batch) and
    # retry with a SAVEPOINT per row, which is the only way to keep
    # collecting errors past a statement that poisoned the fast pass.
    try:
        async with db.begin_nested():
            success_count, apply_errors = await _run_apply_pass(
                db, parsed, spec, use_savepoints=False
            )
    except _NeedsSavepointRetry:
        with _ref_cache_scope(db):
            success_count, apply_errors = await _run_apply_pass(
                db, parsed, spec, use_savepoints=True
            )

    return _SingleResult(
        parsed_rows=len(rows),
        ok_rows=success_count,
        error_rows=apply_errors,
        warnings=warnings,
    )


async def run_import(
    db: AsyncSession,
    entity: str,
    content: bytes,
    dry_run: bool,
    *,
    column_map: dict[str, str | None] | None = None,
) -> ImportReport:
    if column_map:
        content = apply_column_mapping(content, column_map)
    with _ref_cache_scope(db):
        result = await _import_one(db, entity, content)

    if result.error_rows or dry_run:
        await db.rollback()
        return ImportReport(
            parsed_rows=result.parsed_rows,
            ok_rows=result.ok_rows,
            error_rows=result.error_rows,
            applied=False,
            warnings=result.warnings,
        )

    await db.commit()
    return ImportReport(
        parsed_rows=result.parsed_rows,
        ok_rows=result.ok_rows,
        error_rows=[],
        applied=True,
        warnings=result.warnings,
    )


async def run_bulk_import(
    db: AsyncSession,
    files: list[tuple[str, bytes]],
    dry_run: bool,
) -> BulkImportReport:
    """Detect → order → apply, all inside a single transaction.

    Any file failure aborts the whole batch. `dry_run=True` always rolls back
    even if every file would have applied cleanly. Reports are per-file so
    the UI can pinpoint which CSV caused the rollback.
    """
    if not files:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "NO_FILES",
                    "message": "No CSV file supplied.",
                }
            },
        )
    if len(files) > BULK_MAX_FILES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "TOO_MANY_FILES",
                    "message": (
                        f"At most {BULK_MAX_FILES} files per bulk import "
                        f"(got {len(files)})."
                    ),
                }
            },
        )
    total_bytes = sum(len(c) for _, c in files)
    if total_bytes > BULK_MAX_TOTAL_BYTES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "BULK_TOO_LARGE",
                    "message": (
                        f"Total upload size {total_bytes} exceeds the "
                        f"{BULK_MAX_TOTAL_BYTES} byte bulk limit."
                    ),
                }
            },
        )

    # ---- Phase 1: detect entity for every file ---------------------------
    detections: list[tuple[str, bytes, DetectReport]] = []
    file_reports: list[BulkImportFileReport] = []
    any_detect_error = False
    for filename, content in files:
        det = detect_entity(content)
        if det.entity is None:
            any_detect_error = True
            file_reports.append(
                BulkImportFileReport(
                    filename=filename,
                    detected_entity=None,
                    parsed_rows=0,
                    ok_rows=0,
                    error_rows=[
                        ImportErrorRow(
                            line=1,
                            column=None,
                            value=None,
                            error=(
                                "Could not detect the entity from the header row. "
                                + (
                                    f"Closest match would need columns: "
                                    f"{', '.join(det.missing_required)}."
                                    if det.missing_required
                                    else "Header row is empty."
                                )
                            ),
                        )
                    ],
                )
            )
        else:
            detections.append((filename, content, det))

    if any_detect_error:
        # Don't even start the transaction — surface every file we couldn't
        # route so the user can fix all of them at once.
        for filename, _, det in detections:
            file_reports.append(
                BulkImportFileReport(
                    filename=filename,
                    detected_entity=det.entity,
                    parsed_rows=0,
                    ok_rows=0,
                    error_rows=[],
                )
            )
        return BulkImportReport(
            files=_sort_bulk_reports(file_reports),
            total_parsed_rows=0,
            total_ok_rows=0,
            applied=False,
        )

    # ---- Phase 2: apply in dependency order ------------------------------
    detections.sort(key=lambda t: IMPORT_ORDER.index(t[2].entity))  # type: ignore[arg-type]

    total_parsed = 0
    total_ok = 0
    had_error = False
    # One cache for the whole batch, not one per file: `rooms.csv` must be
    # able to resolve a site `sites.csv` created two files earlier without
    # paying for a re-read.
    with _ref_cache_scope(db):
        for filename, content, det in detections:
            assert det.entity is not None  # phase 1 filtered the Nones out
            result = await _import_one(db, det.entity, content)
            total_parsed += result.parsed_rows
            total_ok += result.ok_rows
            file_reports.append(
                BulkImportFileReport(
                    filename=filename,
                    detected_entity=det.entity,
                    parsed_rows=result.parsed_rows,
                    ok_rows=result.ok_rows,
                    error_rows=result.error_rows,
                    warnings=result.warnings,
                )
            )
            if result.error_rows:
                had_error = True
                break

    # Files we skipped after the first failure still get reported so the UI
    # can show "pending" rather than silently dropping them.
    seen = {fr.filename for fr in file_reports}
    for filename, _, det in detections:
        if filename in seen:
            continue
        file_reports.append(
            BulkImportFileReport(
                filename=filename,
                detected_entity=det.entity,
                parsed_rows=0,
                ok_rows=0,
                error_rows=[],
            )
        )

    if had_error or dry_run:
        await db.rollback()
        return BulkImportReport(
            files=_sort_bulk_reports(file_reports),
            total_parsed_rows=total_parsed,
            total_ok_rows=total_ok,
            applied=False,
        )

    await db.commit()
    return BulkImportReport(
        files=_sort_bulk_reports(file_reports),
        total_parsed_rows=total_parsed,
        total_ok_rows=total_ok,
        applied=True,
    )


def _sort_bulk_reports(reports: list[BulkImportFileReport]) -> list[BulkImportFileReport]:
    """Stable display order: detected files in dependency order, then any
    undetected file (kept at the end so they're visually grouped)."""

    def key(r: BulkImportFileReport) -> tuple[int, str]:
        if r.detected_entity is None:
            return (len(IMPORT_ORDER), r.filename)
        return (IMPORT_ORDER.index(r.detected_entity), r.filename)

    return sorted(reports, key=key)
