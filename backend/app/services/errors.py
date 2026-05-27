"""Map SQLAlchemy / PostgreSQL exceptions to HTTPException with stable codes.

Every CRUD service wraps DB writes in `catch_integrity_errors()`. The
mapping is centralized here so all routers produce the same error shape:

    { "error": { "code": "<UPPER_SNAKE>", "message": "<human-readable>" } }
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import NoReturn

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError


def http_error(
    status_code: int, code: str, message: str, details: dict | None = None
) -> NoReturn:
    payload: dict = {"error": {"code": code, "message": message}}
    if details:
        payload["error"]["details"] = details
    raise HTTPException(status_code=status_code, detail=payload)


def not_found(entity: str, entity_id: int | str) -> NoReturn:
    http_error(
        status.HTTP_404_NOT_FOUND,
        "NOT_FOUND",
        f"{entity} {entity_id!r} does not exist.",
    )


def conflict(code: str, message: str, details: dict | None = None) -> NoReturn:
    http_error(status.HTTP_409_CONFLICT, code, message, details)


def business_rule(code: str, message: str, details: dict | None = None) -> NoReturn:
    http_error(status.HTTP_400_BAD_REQUEST, code, message, details)


# Stable codes returned for known DB-level constraint violations.
# Routers can rely on these to surface helpful messages in the UI.
_CONSTRAINT_CODES: dict[str, tuple[str, str]] = {
    # Subnets — the GiST exclusion was split into two scoped constraints in
    # migration 0010 (one for the global VRF, one keyed by vrf_id). Both
    # map to the same user-facing SUBNET_OVERLAP code so the UI logic
    # doesn't need to know which scope tripped.
    "subnets_no_overlap_global": (
        "SUBNET_OVERLAP",
        "This CIDR overlaps an existing subnet.",
    ),
    "subnets_no_overlap_vrf": (
        "SUBNET_OVERLAP",
        "This CIDR overlaps another subnet in the same VRF.",
    ),
    # Legacy name — kept so downgraded installs still surface the friendly
    # error. Harmless when only the new constraints are present.
    "subnets_no_overlap": (
        "SUBNET_OVERLAP",
        "This CIDR overlaps an existing subnet.",
    ),
    # Sites
    "sites_code_key": ("DUPLICATE_CODE", "A site with this code already exists."),
    # Rooms
    "rooms_site_code_uniq": (
        "DUPLICATE_CODE",
        "A room with this code already exists in this site.",
    ),
    # VLANs
    "vlans_vlan_id_key": (
        "DUPLICATE_VLAN_ID",
        "A VLAN with this ID already exists.",
    ),
    "vlans_id_range": (
        "VLAN_ID_OUT_OF_RANGE",
        "VLAN id must be between 1 and 4094.",
    ),
    # IPs
    "ips_address_key": (
        "DUPLICATE_IP",
        "This IP address is already registered.",
    ),
    # Switches
    "switches_name_key": (
        "DUPLICATE_NAME",
        "A switch with this name already exists.",
    ),
    "ports_switch_number_uniq": (
        "DUPLICATE_PORT",
        "A port with this number already exists on this switch.",
    ),
    # Links
    "links_ports_uniq": (
        "DUPLICATE_LINK",
        "A link between these two ports already exists.",
    ),
    "links_distinct_ports": (
        "INVALID_LINK",
        "A link cannot connect a port to itself.",
    ),
}


def _match_constraint(message: str) -> tuple[str, str] | None:
    """Best-effort match of a PG constraint name in the error message."""
    for name, code_msg in _CONSTRAINT_CODES.items():
        if name in message:
            return code_msg
    return None


# Public alias for callers that need to map an `IntegrityError` raised
# OUTSIDE a `catch_integrity_errors()` context — e.g. the AI draft
# applier rolls back + re-raises before the route layer gets it, so the
# route layer has to translate the constraint name itself. Keep the
# leading-underscore version too because `_match_constraint` is what
# the existing private callers reference.
match_constraint = _match_constraint


@contextmanager
def catch_integrity_errors():
    """Translate IntegrityError → HTTPException with a stable code.

    Falls back to a generic 409 if the constraint isn't recognised — better
    than leaking SQLAlchemy internals to the client.
    """
    try:
        yield
    except IntegrityError as exc:
        msg = str(getattr(exc, "orig", exc))
        match = _match_constraint(msg)
        if match:
            code, friendly = match
            conflict(code, friendly)
        # Unknown constraint — surface a generic conflict.
        conflict("INTEGRITY_VIOLATION", "Data integrity violation.")
