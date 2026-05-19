"""Tests for the DB-error → HTTPException mapper."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.services.errors import (
    business_rule,
    catch_integrity_errors,
    conflict,
    http_error,
    not_found,
)


def _fake_integrity_error(constraint: str) -> IntegrityError:
    orig = Exception(f'duplicate key value violates constraint "{constraint}"')
    return IntegrityError(statement="INSERT ...", params={}, orig=orig)


def test_subnet_overlap_constraint_is_mapped_to_409() -> None:
    with pytest.raises(HTTPException) as exc, catch_integrity_errors():
        raise _fake_integrity_error("subnets_no_overlap")
    assert exc.value.status_code == 409
    assert exc.value.detail["error"]["code"] == "SUBNET_OVERLAP"


def test_duplicate_site_code_is_mapped_to_409() -> None:
    with pytest.raises(HTTPException) as exc, catch_integrity_errors():
        raise _fake_integrity_error("sites_code_key")
    assert exc.value.status_code == 409
    assert exc.value.detail["error"]["code"] == "DUPLICATE_CODE"


def test_duplicate_room_code_in_site_is_mapped_to_409() -> None:
    with pytest.raises(HTTPException) as exc, catch_integrity_errors():
        raise _fake_integrity_error("rooms_site_code_uniq")
    assert exc.value.status_code == 409
    assert exc.value.detail["error"]["code"] == "DUPLICATE_CODE"


def test_duplicate_vlan_id_is_mapped_to_409() -> None:
    with pytest.raises(HTTPException) as exc, catch_integrity_errors():
        raise _fake_integrity_error("vlans_vlan_id_key")
    assert exc.value.status_code == 409
    assert exc.value.detail["error"]["code"] == "DUPLICATE_VLAN_ID"


def test_unknown_constraint_falls_back_to_generic_409() -> None:
    with pytest.raises(HTTPException) as exc, catch_integrity_errors():
        raise _fake_integrity_error("some_unknown_constraint_xyz")
    assert exc.value.status_code == 409
    assert exc.value.detail["error"]["code"] == "INTEGRITY_VIOLATION"


def test_not_found_raises_404_with_code() -> None:
    with pytest.raises(HTTPException) as exc:
        not_found("Site", 42)
    assert exc.value.status_code == 404
    assert exc.value.detail["error"]["code"] == "NOT_FOUND"


def test_business_rule_raises_400_with_code_and_details() -> None:
    with pytest.raises(HTTPException) as exc:
        business_rule(
            "IP_NOT_IN_SUBNET",
            "x not in y",
            details={"address": "10.0.0.5", "cidr": "10.0.30.0/24"},
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["error"]["code"] == "IP_NOT_IN_SUBNET"
    assert exc.value.detail["error"]["details"]["address"] == "10.0.0.5"


def test_conflict_helper() -> None:
    with pytest.raises(HTTPException) as exc:
        conflict("X", "y")
    assert exc.value.status_code == 409


def test_http_error_helper_is_generic() -> None:
    with pytest.raises(HTTPException) as exc:
        http_error(418, "TEAPOT", "I am one")
    assert exc.value.status_code == 418
    assert exc.value.detail["error"]["code"] == "TEAPOT"


def test_catch_integrity_does_not_swallow_other_exceptions() -> None:
    with pytest.raises(ValueError), catch_integrity_errors():
        _ = MagicMock()  # keep MagicMock used
        raise ValueError("not an integrity error")
