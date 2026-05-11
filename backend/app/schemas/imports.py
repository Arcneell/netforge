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
