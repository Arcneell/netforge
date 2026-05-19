"""Tests for the `apply_column_mapping` helper that backs the AI-assisted
auto-rename flow.

We don't run the full import — the helper's contract is "rewrite the header
row, leave the body alone, drop columns mapped to None". The import service
already has its own tests for the row parsing.
"""

from __future__ import annotations

from app.services.csv_import import apply_column_mapping


def _utf8(text: str) -> bytes:
    """Encoder that matches the production import pipeline (utf-8-sig)."""
    return text.encode("utf-8-sig")


def _decode(content: bytes) -> str:
    return content.decode("utf-8-sig", errors="replace")


def test_rename_known_columns_and_leave_others_alone() -> None:
    csv = _utf8("Subnet;GW;Site\n10.0.0.0/24;10.0.0.1;PAR\n10.0.1.0/24;;LYO\n")
    out = apply_column_mapping(
        csv,
        {"Subnet": "cidr", "GW": "gateway", "Site": "site_code"},
    )
    text = _decode(out)
    assert text.splitlines()[0] == "cidr;gateway;site_code"
    # Bodies are untouched.
    assert "10.0.0.0/24;10.0.0.1;PAR" in text


def test_columns_not_in_mapping_pass_through() -> None:
    csv = _utf8("Subnet;GW;Notes\n10.0.0.0/24;10.0.0.1;hello\n")
    out = apply_column_mapping(
        csv,
        {"Subnet": "cidr"},  # only the first column is mapped
    )
    text = _decode(out)
    # `GW` and `Notes` survive verbatim — the import will ignore them
    # because pydantic drops extras.
    assert text.splitlines()[0] == "cidr;GW;Notes"


def test_columns_mapped_to_none_are_dropped_from_every_row() -> None:
    csv = _utf8("Subnet;Junk;Site\n10.0.0.0/24;XXX;PAR\n10.0.1.0/24;YYY;LYO\n")
    out = apply_column_mapping(
        csv,
        {"Subnet": "cidr", "Junk": None, "Site": "site_code"},
    )
    lines = _decode(out).splitlines()
    assert lines[0] == "cidr;site_code"
    assert lines[1] == "10.0.0.0/24;PAR"
    assert lines[2] == "10.0.1.0/24;LYO"
    assert "XXX" not in _decode(out)


def test_empty_mapping_returns_input_unchanged() -> None:
    csv = _utf8("a;b\n1;2\n")
    out = apply_column_mapping(csv, {})
    assert out == csv


def test_empty_csv_does_not_crash() -> None:
    out = apply_column_mapping(b"", {"x": "y"})
    assert out == b""


def test_short_row_pads_with_blank_when_missing_trailing_cell() -> None:
    """If the source CSV has rows with fewer cells than the header (some
    exporters do this when the last cell is blank), the rewrite must not
    crash — we substitute an empty string."""
    csv = _utf8("a;b;c\n1;2\n3\n")
    out = apply_column_mapping(csv, {"a": "x", "b": "y", "c": "z"})
    lines = _decode(out).splitlines()
    assert lines == ["x;y;z", "1;2;", "3;;"]
