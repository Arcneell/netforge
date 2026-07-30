"""Audit log helpers — pure-function tests for the JSON-safe dump and diff.

End-to-end testing of the SQLAlchemy event listeners requires a real
Postgres (so they actually fire on INSERT/UPDATE/DELETE) and is deferred
to phase 3.5 (`testcontainers-postgres`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

import pytest

from app.models.core import Site
from app.models.port import PortMode
from app.models.switch import Switch
from app.models.user import AuditAction
from app.services.audit import (
    SENSITIVE_FIELDS,
    _dump_columns,
    _jsonsafe,
    current_request_ip_var,
    current_request_ua_var,
    current_user_id_var,
    redact_sensitive,
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

    Cleanup uses the precise `reset_audit_listeners` helper from the
    audit module (which tracks the exact (model, evt, fn) tuples it
    attached) so no orphaned wrapped closures are left on any mapper
    after this test runs — that was the Codex P2 on #87.
    """
    from app.services.audit import reset_audit_listeners

    # Drop everything we previously attached, then re-attach exactly once.
    reset_audit_listeners()
    register_audit_listeners()
    after_first = _count_after_insert(Site)
    assert after_first >= 1, "first call must attach at least one listener"

    register_audit_listeners()
    register_audit_listeners()
    assert _count_after_insert(Site) == after_first, (
        "subsequent calls must be no-ops"
    )


# --- redact_sensitive (Fix #3: snmp_community must never leak in plaintext) -


def test_sensitive_fields_lists_snmp_community() -> None:
    assert "snmp_community" in SENSITIVE_FIELDS


def test_redact_sensitive_masks_snmp_community() -> None:
    out = redact_sensitive({"id": 1, "name": "SW-01", "snmp_community": "public"})
    assert out["snmp_community"] == "***"
    assert out["id"] == 1
    assert out["name"] == "SW-01"


def test_redact_sensitive_leaves_null_snmp_community_as_null() -> None:
    """A column that was never set shouldn't be turned into the literal
    string "***" — that would look like a real (masked) secret was present
    when there wasn't one."""
    out = redact_sensitive({"snmp_community": None})
    assert out["snmp_community"] is None


def test_redact_sensitive_is_noop_for_unrelated_dicts() -> None:
    data = {"code": "HQ", "name": "Headquarters"}
    assert redact_sensitive(data) == data


def test_dump_columns_of_switch_exposes_raw_value_before_redaction() -> None:
    """`_dump_columns` itself is a raw snapshot — masking is applied by the
    caller (`_attach_listeners`'s `_on_insert`/`_on_update`/`_on_delete`).
    Pin that contract so a future refactor doesn't accidentally bake
    redaction into the wrong layer or drop it entirely."""
    switch = Switch(
        id=1, name="SW-01", port_count=48, snmp_community="public"
    )
    dump = _dump_columns(switch)
    assert dump["snmp_community"] == "public"
    assert redact_sensitive(dump)["snmp_community"] == "***"


# --- audit_log retention purge ---------------------------------------------
#
# Same lazy-cleanup idiom as `webhook_deliveries` (services/webhooks.py) and
# `rate_limit_counters` (services/rate_limit_store.py), anchored on
# `_write_audit_row`'s `Connection` instead of a dispatcher/scheduler loop —
# see the module docstring. End-to-end (a real INSERT actually triggering a
# DELETE) needs Postgres and is deferred to the testcontainers suite, same
# as the listener wiring above; these pin the throttle + on/off contract.


def test_maybe_purge_audit_log_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import MagicMock

    from app.config import get_settings
    from app.services.audit import _maybe_purge_audit_log, reset_audit_purge_clock

    monkeypatch.delenv("AUDIT_LOG_RETENTION_DAYS", raising=False)
    get_settings.cache_clear()
    reset_audit_purge_clock()
    try:
        conn = MagicMock()
        _maybe_purge_audit_log(conn)
        conn.execute.assert_not_called()
    finally:
        get_settings.cache_clear()
        reset_audit_purge_clock()


def test_maybe_purge_audit_log_runs_once_per_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enabling retention (`AUDIT_LOG_RETENTION_DAYS > 0`) issues the DELETE
    on the first audited mutation, then stays quiet for the rest of the
    throttle interval — same contract as `rate_limit_store.maybe_purge_expired`."""
    from unittest.mock import MagicMock

    from app.config import get_settings
    from app.services.audit import _maybe_purge_audit_log, reset_audit_purge_clock

    monkeypatch.setenv("AUDIT_LOG_RETENTION_DAYS", "30")
    get_settings.cache_clear()
    reset_audit_purge_clock()
    try:
        conn = MagicMock()
        _maybe_purge_audit_log(conn)
        _maybe_purge_audit_log(conn)
        _maybe_purge_audit_log(conn)
        assert conn.execute.call_count == 1
    finally:
        monkeypatch.delenv("AUDIT_LOG_RETENTION_DAYS", raising=False)
        get_settings.cache_clear()
        reset_audit_purge_clock()


# --- webhook outbox wiring (durable handoff, Codex audit follow-up) ---------
#
# `_write_audit_row` now also persists a `webhook_outbox` row on the SAME
# `Connection` it already uses for `insert(AuditLog)` — see
# `services/webhooks.py::write_outbox_row`. Real transactional rollback
# semantics need a real Postgres and are covered end-to-end in
# `tests/integration/test_webhook_outbox_pg.py`; here we pin that
# `_write_audit_row` hands `write_outbox_row` the exact same `Connection`
# object, which is what makes "same transaction" true in the first place.


def test_write_audit_row_persists_outbox_row_on_the_same_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import MagicMock

    import app.services.webhooks as webhooks_module
    from app.services.audit import _write_audit_row

    seen: dict[str, object] = {}

    def fake_write_outbox_row(connection: object, event: object) -> None:
        seen["connection"] = connection
        seen["event"] = event

    # `_write_audit_row` imports `write_outbox_row` locally (function-local
    # `from app.services.webhooks import ...`), so patching the attribute on
    # `app.services.webhooks` itself — not a name bound inside `audit.py` —
    # is what actually takes effect at call time.
    monkeypatch.setattr(webhooks_module, "write_outbox_row", fake_write_outbox_row)

    conn = MagicMock()
    _write_audit_row(conn, AuditAction.create, "site", 1, {"after": {"code": "HQ"}})

    assert seen["connection"] is conn
    assert seen["event"].event_name == "site.create"
    assert seen["event"].entity_id == 1


def test_write_audit_row_outbox_event_carries_the_before_after_diff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The `WebhookEvent` handed to `write_outbox_row` must be built from
    the SAME `before`/`after` the audit row itself records — the outbox
    payload and `audit_log.changes` must never diverge. Runs through the
    REAL `write_outbox_row` (only the `Connection` is a mock) so this also
    pins that `event.outbox_id` ends up set from the mocked
    `RETURNING id` result."""
    from unittest.mock import MagicMock

    from app.services.audit import _write_audit_row

    conn = MagicMock()
    conn.execute.return_value.scalar_one.return_value = 99

    _write_audit_row(
        conn,
        AuditAction.update,
        "port",
        7,
        {"before": {"label": "old"}, "after": {"label": "new"}},
    )

    # Two inserts on the same connection: audit_log, then webhook_outbox.
    assert conn.execute.call_count == 2
    outbox_stmt = conn.execute.call_args_list[1].args[0]
    params = outbox_stmt.compile().params
    assert params["payload"]["before"] == {"label": "old"}
    assert params["payload"]["after"] == {"label": "new"}

