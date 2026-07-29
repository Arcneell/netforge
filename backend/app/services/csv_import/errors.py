"""Error types and error → report mapping for the CSV importer.

Kept apart from the resolvers and the persist layer because both raise these
and the driver is the only thing that turns them into `ImportErrorRow`s.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.schemas.imports import ImportErrorRow


class _RefError(Exception):
    """Raised when a CSV row points at an entity that does not exist."""

    def __init__(self, column: str, value: Any, message: str) -> None:
        self.column = column
        self.value = "" if value is None else str(value)
        self.message = message
        super().__init__(message)


def _format_validation_errors(
    line: int, raw: dict[str, str], exc: ValidationError
) -> list[ImportErrorRow]:
    out: list[ImportErrorRow] = []
    for err in exc.errors():
        loc = err.get("loc", ())
        column = str(loc[0]) if loc else None
        out.append(
            ImportErrorRow(
                line=line,
                column=column,
                value=raw.get(column, "") if column else None,
                error=err.get("msg", "validation error"),
            )
        )
    return out


def _friendly_integrity(msg: str) -> str:
    """Surface the underlying DB constraint name without leaking the full
    SQLAlchemy traceback to the API caller."""
    for hint, friendly in (
        ("subnets_no_overlap", "CIDR overlaps an existing subnet"),
        ("sites_code_key", "site code already exists"),
        ("rooms_site_code_uniq", "room code already exists in this site"),
        ("vlans_vlan_id_key", "VLAN id already exists"),
        ("ips_address_key", "IP address already exists"),
        ("switches_name_key", "switch name already exists"),
        ("ports_switch_number_uniq", "port number already exists on this switch"),
        ("links_ports_uniq", "link between these two ports already exists"),
        ("ips_check_in_subnet", "IP is not contained in any registered subnet"),
    ):
        if hint in msg:
            return friendly
    return "database constraint violation"
