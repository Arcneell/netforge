"""Audit log helpers — pure-function tests for the JSON-safe dump and diff.

End-to-end testing of the SQLAlchemy event listeners requires a real
Postgres (so they actually fire on INSERT/UPDATE/DELETE) and is deferred
to phase 3.5 (`testcontainers-postgres`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import event

from app.models.core import Site
from app.models.port import PortMode
from app.models.user import AuditAction
from app.services import audit as audit_module
from app.services.audit import (
    _dump_columns,
    _jsonsafe,
    current_request_ip_var,
    current_request_ua_var,
    current_user_id_var,
    register_audit_listeners,
)


class _SampleEnum(Enum):
    A = "alpha"
    B = "beta"


def test_jsonsafe_primitives_pass_through() -> None:
    assert _jsonsafe(None) is None
    assert _jsonsafe(True) is True
    assert _jsonsafe(42) == 42
    assert _jsonsafe(3.14) == 3.14
    assert _jsonsafe("hello") == "hello"


def test_jsonsafe_datetime_to_iso() -> None:
    dt = datetime(2026, 4, 24, 15, 30, tzinfo=UTC)
    out = _jsonsafe(dt)
    assert isinstance(out, str)
    assert "2026-04-24" in out


def test_jsonsafe_enum_to_value() -> None:
    assert _jsonsafe(_SampleEnum.A) == "alpha"
    assert _jsonsafe(PortMode.trunk) == "trunk"
    assert _jsonsafe(AuditAction.create) == "create"


def test_jsonsafe_dict_recurses() -> None:
    out = _jsonsafe({"a": _SampleEnum.B, "b": [1, _SampleEnum.A]})
    assert out == {"a": "beta", "b": [1, "alpha"]}


def test_jsonsafe_unknown_type_falls_back_to_str() -> None:
    class Opaque:
        def __str__(self) -> str:
            return "opaque-thing"

    assert _jsonsafe(Opaque()) == "opaque-thing"


def test_dump_columns_serialises_all_model_columns() -> None:
    from app.models.core import Site

    site = Site(id=1, code="HQ", name="Headquarters", address="1 Main St")
    dump = _dump_columns(site)

    assert dump["id"] == 1
    assert dump["code"] == "HQ"
    assert dump["name"] == "Headquarters"
    assert dump["address"] == "1 Main St"


def test_context_var_is_request_scoped() -> None:
    # Default for an unauthenticated request.
    assert current_user_id_var.get() is None

    # Within a scope, the value is whatever was set; resetting restores default.
    token = current_user_id_var.set(42)
    try:
        assert current_user_id_var.get() == 42
    finally:
        current_user_id_var.reset(token)

    assert current_user_id_var.get() is None


def test_request_metadata_context_vars_default_to_none() -> None:
    assert current_request_ip_var.get() is None
    assert current_request_ua_var.get() is None


def test_request_metadata_context_vars_round_trip() -> None:
    ip_tok = current_request_ip_var.set("10.0.0.42")
    ua_tok = current_request_ua_var.set("curl/8.4.0")
    try:
        assert current_request_ip_var.get() == "10.0.0.42"
        assert current_request_ua_var.get() == "curl/8.4.0"
    finally:
        current_request_ip_var.reset(ip_tok)
        current_request_ua_var.reset(ua_tok)

    assert current_request_ip_var.get() is None
    assert current_request_ua_var.get() is None


def _count_after_insert(model: type) -> int:
    return len(model.__mapper__.dispatch.after_insert.listeners)


def test_register_audit_listeners_is_idempotent() -> None:
    """`create_app()` can run more than once in the same process (test
    factories that build a fresh app per fixture, uvicorn --reload, a
    future multi-app harness). Without an idempotency guard every extra
    `register_audit_listeners()` call attached duplicate after_insert /
    after_update / after_delete handlers on every audited model —
    producing N duplicate audit_log rows AND N duplicate webhook
    events per real mutation. Pin the contract: the first call attaches
    the listeners; every subsequent call is a no-op.
    """
    # Ensure we start from a known state by clearing existing listeners
    # and the flag, so the test does not depend on collection order.
    _strip_audit_listeners()
    audit_module._listeners_registered = False

    register_audit_listeners()
    after_first = _count_after_insert(Site)
    assert after_first >= 1, "first call must attach at least one listener"

    register_audit_listeners()
    register_audit_listeners()
    assert _count_after_insert(Site) == after_first, (
        "subsequent calls must be no-ops"
    )


def _strip_audit_listeners() -> None:
    """Remove every audit-registered after_insert/update/delete handler
    on Site. Helper used by the idempotency test to start from a known
    baseline regardless of which other tests ran first.

    SQLAlchemy wraps closures so `remove()` can fail to find the exact
    registered key — best-effort cleanup is fine because the subsequent
    `register_audit_listeners()` will recreate whatever we miss.
    """
    import contextlib

    for evt_name in ("after_insert", "after_update", "after_delete"):
        listeners = list(getattr(Site.__mapper__.dispatch, evt_name).listeners)
        for fn in listeners:
            with contextlib.suppress(Exception):
                event.remove(Site, evt_name, fn)

