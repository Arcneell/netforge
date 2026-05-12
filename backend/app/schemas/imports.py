"""CSV import — request flags + response report."""

from __future__ import annotations

from pydantic import BaseModel


class ImportErrorRow(BaseModel):
    """One failure reported by the import — either a parse/validation error
    flagged before any DB work, or a constraint violation surfaced during
    the apply phase."""

    line: int  # 1-based, including the header line (so the first data row is 2)
    column: str | None = None
    value: str | None = None
    error: str


class ImportReport(BaseModel):
    parsed_rows: int  # rows after the header, both ok and erroring
    ok_rows: int
    error_rows: list[ImportErrorRow]
    applied: bool  # True only when dry_run=False AND no error


class DetectReport(BaseModel):
    """Result of inspecting a CSV's header row to guess which entity it
    belongs to. `entity` is None when no entity has all its required columns
    in the file — `missing_required` then lists what would be needed for the
    closest candidate so the user can fix the file."""

    entity: str | None
    confidence: float  # 0.0 (no match) — 1.0 (perfect, no unknown columns)
    headers: list[str]  # actual header row, in original order
    matched_required: list[str]
    missing_required: list[str]
    unknown_headers: list[str]  # columns we don't know what to do with
    candidates: dict[str, float]  # score per entity — for debugging UIs


class BulkImportFileReport(BaseModel):
    """Per-file outcome inside a bulk import. `detected_entity` is None when
    auto-detection failed; in that case `error_rows` carries the reason."""

    filename: str
    detected_entity: str | None
    parsed_rows: int
    ok_rows: int
    error_rows: list[ImportErrorRow]


class BulkImportReport(BaseModel):
    """Aggregated result of a multi-CSV import. `applied=True` means every
    file committed; any error in any file rolls the whole batch back."""

    files: list[BulkImportFileReport]
    total_parsed_rows: int
    total_ok_rows: int
    applied: bool
