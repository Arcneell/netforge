"""Audit log — captures every ORM mutation on registered models.

How it works:

  - A ContextVar holds the current request's user id (set by the auth
    dependency `get_current_user`). The audit listeners read it when a
    mutation flushes.
  - SQLAlchemy `after_insert`, `after_update`, `after_delete` events on
    each tracked mapper insert one row into `audit_log` using the same
    `Connection` — so the audit row commits atomically with the mutation.

What we **do not** audit:
  - `users`, `sessions` (auth plumbing; would create infinite recursion
    during login / JIT user creation).
  - `audit_log` itself.
  - `port_vlan` (no integer PK; the parent `ports` mutation is logged
    anyway).

Retention: unlike `webhook_deliveries` (services/webhooks.py) and
`ai_run_logs` (services/ai/scheduler.py), `audit_log` has no background loop
or request-scoped dispatcher of its own to hang a lazy purge off — every
audited mutation runs `_write_audit_row` on the SAME `Connection` already
open for that mutation, so that's where the purge lives too (see
`_maybe_purge_audit_log`), gated by `Settings.audit_log_retention_days`
(0 = disabled, the conservative default for an audit trail).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from contextvars import ContextVar
from datetime import UTC, date, datetime, timedelta
from enum import Enum
from typing import Any

from sqlalchemy import delete, event, insert
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapper

from app.config import get_settings
from app.models.core import Room, Site
from app.models.device import Device
from app.models.ip import Ip
from app.models.link import Link
from app.models.port import Port
from app.models.subnet import Subnet
from app.models.switch import Switch
from app.models.user import AuditAction, AuditLog
from app.models.vlan import Vlan

# Set by the auth dependency at the start of an authenticated request.
# None means "no user identified yet" (login / callback paths) — the
# audit row is still written, with user_id NULL.
current_user_id_var: ContextVar[int | None] = ContextVar(
    "current_user_id", default=None
)

# Set by the HTTP middleware in `app/main.py` at the very start of each
# request, so they're visible from inside the SQLAlchemy event listeners
# (which have no Request handle of their own).
current_request_ip_var: ContextVar[str | None] = ContextVar(
    "current_request_ip", default=None
)
current_request_ua_var: ContextVar[str | None] = ContextVar(
    "current_request_ua", default=None
)


# Column names whose raw value must never leave the process boundary —
# not in an audit_log.changes row, not in a webhook payload — even though
# the value lives in plaintext in the DB (e.g. `Switch.snmp_community`).
# `webhooks.WebhookEvent.to_payload` re-applies `redact_sensitive` on its
# own before/after dicts as a second line of defence, since `before`/
# `after` there are built from the same `changes` dict this module writes.
SENSITIVE_FIELDS: frozenset[str] = frozenset({"snmp_community"})


def redact_sensitive(data: dict[str, Any]) -> dict[str, Any]:
    """Mask sensitive column values before they're persisted or dispatched."""
    return {
        key: ("***" if key in SENSITIVE_FIELDS and value is not None else value)
        for key, value in data.items()
    }


# (Model, entity name written into audit_log.entity)
_AUDITED: list[tuple[type, str]] = [
    (Site, "site"),
    (Room, "room"),
    (Vlan, "vlan"),
    (Subnet, "subnet"),
    (Ip, "ip"),
    (Device, "device"),
    (Switch, "switch"),
    (Port, "port"),
    (Link, "link"),
]


def _jsonsafe(value: Any) -> Any:
    """Coerce DB values to JSON-friendly primitives."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (list, tuple)):
        return [_jsonsafe(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonsafe(v) for k, v in value.items()}
    return str(value)


def _dump_columns(instance: Any) -> dict[str, Any]:
    """Snapshot of every column-mapped attribute of `instance`."""
    mapper: Mapper = instance.__mapper__
    out: dict[str, Any] = {}
    for col in mapper.columns:
        out[col.key] = _jsonsafe(getattr(instance, col.key, None))
    return out


def _diff_changed_columns(instance: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (before, after) for the columns that actually changed."""
    from sqlalchemy import inspect as sa_inspect

    state = sa_inspect(instance)
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for attr in state.attrs:
        history = attr.history
        if not history.has_changes():
            continue
        before[attr.key] = _jsonsafe(history.deleted[0]) if history.deleted else None
        after[attr.key] = _jsonsafe(history.added[0]) if history.added else None
    return before, after


def _entity_id_of(instance: Any) -> int | None:
    pk = getattr(instance, "id", None)
    return int(pk) if pk is not None else None


def _write_audit_row(
    connection: Connection,
    action: AuditAction,
    entity: str,
    entity_id: int | None,
    changes: dict[str, Any],
) -> None:
    connection.execute(
        insert(AuditLog).values(
            user_id=current_user_id_var.get(),
            action=action.value,
            entity=entity,
            entity_id=entity_id,
            # JSONB columns expect a dict; asyncpg encodes it. We round-trip
            # via json.dumps/loads to guarantee no non-serializable nested
            # values slipped through.
            changes=json.loads(json.dumps(changes, default=str)),
            ip_address=current_request_ip_var.get(),
            user_agent=current_request_ua_var.get(),
        )
    )
    # Queue an outbound webhook event for this mutation. Dispatch is
    # deferred until after the response is known to be successful — see
    # `services/webhooks.py::dispatch_committed_in_background`.
    from app.services.webhooks import queue_event, write_outbox_row

    webhook_event = queue_event(
        entity=entity,
        action=action.value,
        entity_id=entity_id,
        before=changes.get("before") if isinstance(changes, dict) else None,
        after=changes.get("after") if isinstance(changes, dict) else None,
        user_id=current_user_id_var.get(),
    )
    # Persist the same event into `webhook_outbox` on THIS connection — the
    # same durability guarantee `insert(AuditLog)` above already has. Same
    # transaction, same commit/rollback fate. See `write_outbox_row`'s
    # docstring and the `webhook_outbox` module comment in
    # `app/models/webhook.py` for the full rationale (Codex audit: the
    # committed-events ContextVar had nothing durable behind it, so a
    # process crash between commit and the fire-and-forget dispatch lost
    # the event for good).
    write_outbox_row(connection, webhook_event)

    _maybe_purge_audit_log(connection)


# How often a mutation bothers checking for stale rows to purge. Same lazy-
# cleanup idiom as `webhook_deliveries` (services/webhooks.py) and
# `ai_run_logs` (services/ai/scheduler.py) — the difference is *where* it's
# anchored: those two hang off a dispatcher/scheduler loop that only exists
# for their own feature, `audit_log` grows on every audited mutation, so the
# check rides along on the same `_write_audit_row` call instead.
_AUDIT_PURGE_INTERVAL = timedelta(hours=6)
_last_audit_purge_at: datetime | None = None


def _maybe_purge_audit_log(connection: Connection) -> None:
    """Trim `audit_log` rows older than `Settings.audit_log_retention_days`.

    Disabled by default (`audit_log_retention_days=0`) — unlike
    `webhook_deliveries` / `ai_run_logs`, an audit trail is exactly the data
    an operator would NOT want silently aged out, so unlimited retention is
    the safe default. When enabled, runs at most once per
    `_AUDIT_PURGE_INTERVAL` and reuses the `Connection` already open for the
    mutation that triggered this listener — no extra session, no extra
    round trip just to acquire one.
    """
    global _last_audit_purge_at
    retention_days = get_settings().audit_log_retention_days
    if retention_days <= 0:
        return
    now = datetime.now(UTC)
    if (
        _last_audit_purge_at is not None
        and now - _last_audit_purge_at < _AUDIT_PURGE_INTERVAL
    ):
        return
    _last_audit_purge_at = now
    cutoff = now - timedelta(days=retention_days)
    connection.execute(delete(AuditLog).where(AuditLog.created_at < cutoff))


def reset_audit_purge_clock() -> None:
    """Test hook — forget when the last purge ran (mirrors
    `rate_limit_store.reset_purge_clock`)."""
    global _last_audit_purge_at
    _last_audit_purge_at = None


_listeners_registered = False
# Track the (model, evt_name, fn) tuples we attached so the test helper
# `reset_audit_listeners` can remove them precisely. SQLAlchemy wraps
# the closures internally, so a blind `event.remove` with the original
# function reference works when we use it directly — but only if we
# have the reference. Hence this list.
_attached: list[tuple[type, str, Callable[..., Any]]] = []


def register_audit_listeners() -> None:
    """Idempotent: wires after_* events on every audited model.

    The idempotency guard matters because `create_app()` can run more
    than once in the same Python process (test factories that build a
    fresh app per fixture, uvicorn --reload picking up a code change,
    a future multi-app harness). `event.listens_for` happily attaches
    a NEW handler every call — without the flag we end up with N
    duplicate listeners, which produce N duplicate audit_log rows AND
    N duplicate webhook events per mutation.
    """
    global _listeners_registered
    if _listeners_registered:
        return
    for model, entity in _AUDITED:
        _attach_listeners(model, entity)
    _listeners_registered = True


def reset_audit_listeners() -> None:
    """Remove every listener attached by `register_audit_listeners`.

    Test-only helper. Production code never reaches this path: the
    idempotency flag means even a second `register_audit_listeners()`
    call is a no-op, so there is nothing legitimate to undo. Tests
    that need to exercise the registration loop in isolation call
    `reset_audit_listeners()` to get back to a clean slate exactly —
    no orphaned wrapped closures left on any mapper.
    """
    global _listeners_registered
    for model, evt_name, fn in _attached:
        # event.remove accepts the original (pre-wrap) function we
        # stored; SQLAlchemy resolves it back to the wrapper. Best-
        # effort: a listener we attached can have been hand-removed
        # by a previous test using `event.remove` directly.
        import contextlib

        with contextlib.suppress(Exception):
            event.remove(model, evt_name, fn)
    _attached.clear()
    _listeners_registered = False


def _attach_listeners(model: type, entity: str) -> None:
    def _on_insert(mapper, connection, target) -> None:
        _write_audit_row(
            connection,
            AuditAction.create,
            entity,
            _entity_id_of(target),
            {"after": redact_sensitive(_dump_columns(target))},
        )

    def _on_update(mapper, connection, target) -> None:
        before, after = _diff_changed_columns(target)
        # Skip no-op UPDATEs (e.g. server-side updated_at refresh only).
        if not before and not after:
            return
        _write_audit_row(
            connection,
            AuditAction.update,
            entity,
            _entity_id_of(target),
            {"before": redact_sensitive(before), "after": redact_sensitive(after)},
        )

    def _on_delete(mapper, connection, target) -> None:
        _write_audit_row(
            connection,
            AuditAction.delete,
            entity,
            _entity_id_of(target),
            {"before": redact_sensitive(_dump_columns(target))},
        )

    # Wire each handler via the imperative API (instead of @event.listens_for)
    # so we keep the exact callable in `_attached` for later precise removal
    # in `reset_audit_listeners`. The decorator form discards that reference.
    for evt_name, fn in (
        ("after_insert", _on_insert),
        ("after_update", _on_update),
        ("after_delete", _on_delete),
    ):
        event.listen(model, evt_name, fn)
        _attached.append((model, evt_name, fn))
