"""Byte-level handling of the uploaded payloads.

Decoding, delimiter, header rewriting and ZIP explosion — everything that
happens before a single row is validated, plus the size caps that bound the
memory and transaction time of a bulk upload.
"""

from __future__ import annotations

import csv
import io
import zipfile

from fastapi import HTTPException

# Hard caps to keep memory + transaction time bounded. Tuned so a full
# round-trip of `/api/exports/all` always fits.
BULK_MAX_FILES = 50
BULK_MAX_TOTAL_BYTES = 50 * 1024 * 1024  # 50 MiB total across all CSVs
ZIP_MAX_UNCOMPRESSED = 50 * 1024 * 1024  # guard against zip bombs


def _parse_csv(content: bytes) -> list[dict[str, str]]:
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    rows: list[dict[str, str]] = []
    for raw in reader:
        rows.append({(k or "").strip(): (v or "").strip() for k, v in raw.items()})
    return rows


def _read_headers(content: bytes) -> list[str]:
    """Return the column names from the first line of the CSV, or [] if the
    file is empty / unreadable."""
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text), delimiter=";")
    try:
        first = next(reader)
    except StopIteration:
        return []
    return [(h or "").strip() for h in first if h is not None]


def apply_column_mapping(content: bytes, mapping: dict[str, str | None]) -> bytes:
    """Rewrite the header row of a CSV in-memory using `{csv_column → canonical}`.

    - A mapping value of `None` (or a value that resolves to the canonical
      name `null`) means "drop this column entirely" — the rest of the
      rows lose that field as well.
    - Headers absent from the mapping are passed through verbatim, which
      is what lets the AI assistant only worry about the columns it
      successfully identified.
    - The CSV is assumed to use the canonical NetForge encoding (`;`
      delimiter, `utf-8-sig`). Mixed delimiters in the same file are not
      supported because the import pipeline doesn't accept them either.

    Returns the rewritten bytes. The original `content` is not mutated.
    """
    if not mapping:
        return content
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text), delimiter=";")
    try:
        headers = next(reader)
    except StopIteration:
        return content
    # Build per-column decisions in original order: either the rewritten
    # name (and we keep the column) or None (and we drop the column from
    # every row below). Decisions stored as a list of (keep, new_name).
    decisions: list[tuple[bool, str | None]] = []
    for h in headers:
        target = mapping.get(h, h) if h in mapping else h
        if target is None:
            decisions.append((False, None))
        else:
            decisions.append((True, str(target)))
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")
    writer.writerow([new_name for keep, new_name in decisions if keep])
    for row in reader:
        # Skip empty trailing lines without breaking — csv emits a `[]` for
        # them.
        if not row:
            writer.writerow([])
            continue
        writer.writerow(
            [
                row[i] if i < len(row) else ""
                for i, (keep, _new_name) in enumerate(decisions)
                if keep
            ]
        )
    return out.getvalue().encode("utf-8-sig")


def extract_zip(content: bytes) -> list[tuple[str, bytes]]:
    """Pull every .csv member out of a ZIP archive.

    Rejects anything that would expand beyond `ZIP_MAX_UNCOMPRESSED` — defends
    against zip bombs without forcing us to disk-spool. Non-CSV members are
    silently skipped (a backup ZIP may legitimately contain a README).
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "BAD_ZIP",
                    "message": f"ZIP archive is invalid: {exc}",
                }
            },
        ) from exc

    # Bound the decompressed budget against ACTUAL bytes read, not the
    # attacker-supplied `info.file_size` field from the ZIP central
    # directory. A malicious ZIP can declare each member as 1 byte and
    # then explode on `fh.read()` — the previous check (`total +=
    # info.file_size`) accepted that lie and OOM'd the worker.
    out: list[tuple[str, bytes]] = []
    remaining = ZIP_MAX_UNCOMPRESSED
    for info in zf.infolist():
        if info.is_dir():
            continue
        name = info.filename.rsplit("/", 1)[-1]
        if not name.lower().endswith(".csv"):
            continue
        # First-line defence: if the declared size already overflows the
        # remaining budget we can refuse without opening the member. Cheap
        # and catches non-malicious "this export is huge" cases.
        if info.file_size > remaining:
            _raise_zip_too_large()
        with zf.open(info, "r") as fh:
            # Read at most `remaining + 1` so we can detect overflow even
            # when the header lied about the size. The extra byte means
            # we never read more than the cap (limit on the next member
            # is reduced to 0, which triggers the refusal above).
            buf = fh.read(remaining + 1)
            if len(buf) > remaining:
                _raise_zip_too_large()
            remaining -= len(buf)
            out.append((name, buf))
    return out


def _raise_zip_too_large() -> None:
    raise HTTPException(
        status_code=400,
        detail={
            "error": {
                "code": "ZIP_TOO_LARGE",
                "message": (
                    f"ZIP expands to more than "
                    f"{ZIP_MAX_UNCOMPRESSED} bytes uncompressed."
                ),
            }
        },
    )
