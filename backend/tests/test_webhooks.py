"""Pure-function tests for the webhook dispatcher.

The HTTP round-trip and DB persistence sides are covered indirectly by the
audit listener / router tests; here we focus on the small bits that are
easy to get wrong: pattern matching, HMAC signing, payload serialisation,
and the request-scoped ContextVar queue.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from unittest.mock import patch

import pytest

from app.services import webhooks as webhooks_module
from app.services.webhooks import (
    WebhookEvent,
    _drop_pending,
    _promote_pending_to_committed,
    generate_secret,
    matches,
    queue_event,
    sign_body,
    take_committed,
    take_pending,
)

# --- matches() -------------------------------------------------------------


def test_wildcard_matches_anything() -> None:
    assert matches("*", "port.create")
    assert matches("*", "site.update")
    assert matches("*", "webhook.test")


def test_entity_wildcard_matches_only_that_entity() -> None:
    assert matches("port.*", "port.create")
    assert matches("port.*", "port.update")
    assert matches("port.*", "port.delete")
    assert not matches("port.*", "site.create")
    assert not matches("port.*", "switchport.create")  # prefix overlap guard


def test_exact_pattern() -> None:
    assert matches("port.create", "port.create")
    assert not matches("port.create", "port.update")
    assert not matches("port.create", "site.create")


def test_matches_is_case_insensitive() -> None:
    """Patterns are stored lowercased by the schema validator, but the
    matcher lowercases defensively so a stray uppercased event still
    matches."""
    assert matches("Port.*", "port.create")
    assert matches("port.create", "PORT.CREATE")


# --- sign_body() -----------------------------------------------------------


def test_sign_body_is_hmac_sha256_hex_prefixed() -> None:
    body = b'{"hello":"world"}'
    secret = "supersecret"
    signature = sign_body(secret, body)
    assert signature.startswith("sha256=")
    expected = hmac.new(b"supersecret", body, hashlib.sha256).hexdigest()
    assert signature == f"sha256={expected}"


def test_sign_body_is_deterministic_and_secret_dependent() -> None:
    body = b'{"x":1}'
    assert sign_body("a", body) == sign_body("a", body)
    assert sign_body("a", body) != sign_body("b", body)


# --- generate_secret() -----------------------------------------------------


def test_generate_secret_fits_db_column() -> None:
    s = generate_secret()
    assert 32 <= len(s) <= 64  # column is String(64)
    # Two consecutive secrets should differ — sanity check that the RNG
    # is wired up and not returning a constant.
    assert s != generate_secret()


# --- WebhookEvent payload --------------------------------------------------


def test_event_payload_redacts_sensitive_fields() -> None:
    """Fix #3: `snmp_community` (and anything else in
    `audit.SENSITIVE_FIELDS`) must never reach a subscriber in plaintext,
    even if a future caller builds a `WebhookEvent` straight from a raw
    column dump instead of the already-redacted audit `changes` dict."""
    e = WebhookEvent(
        entity="switch",
        action="update",
        entity_id=9,
        before={"snmp_community": "public", "name": "SW-01"},
        after={"snmp_community": "private", "name": "SW-01"},
        user_id=1,
    )
    payload = e.to_payload()
    assert payload["before"]["snmp_community"] == "***"
    assert payload["after"]["snmp_community"] == "***"
    assert payload["before"]["name"] == "SW-01"
    assert payload["after"]["name"] == "SW-01"


def test_event_payload_handles_none_before_after() -> None:
    e = WebhookEvent(
        entity="site", action="create", entity_id=1, before=None, after={"code": "HQ"}, user_id=None
    )
    payload = e.to_payload()
    assert payload["before"] is None
    assert payload["after"] == {"code": "HQ"}


def test_event_payload_has_stable_keys() -> None:
    e = WebhookEvent(
        entity="port",
        action="update",
        entity_id=42,
        before={"label": "old"},
        after={"label": "new"},
        user_id=7,
    )
    payload = e.to_payload()
    assert payload["event"] == "port.update"
    assert payload["entity"] == "port"
    assert payload["action"] == "update"
    assert payload["entity_id"] == 42
    assert payload["before"] == {"label": "old"}
    assert payload["after"] == {"label": "new"}
    assert payload["user_id"] == 7
    # `occurred_at` is ISO-8601 — JSON-serialisable as-is.
    assert isinstance(payload["occurred_at"], str)
    # End-to-end round-trip — should not raise.
    json.dumps(payload, default=str)


# --- queue_event() / take_pending() ---------------------------------------


@pytest.fixture(autouse=True)
def _drain_queue_before_each():
    """Ensure no leakage between tests since the ContextVar is process-wide
    when tests run synchronously (pytest-asyncio gives each test its own
    task, but the default value is shared)."""
    take_pending()
    take_committed()
    yield
    take_pending()
    take_committed()


def test_queue_event_appends_to_request_scoped_bucket() -> None:
    queue_event("site", "create", 1, None, {"name": "HQ"}, user_id=3)
    queue_event("site", "update", 1, {"name": "HQ"}, {"name": "HQ2"}, user_id=3)
    pending = take_pending()
    assert len(pending) == 2
    assert pending[0].event_name == "site.create"
    assert pending[1].event_name == "site.update"
    # Draining clears the queue.
    assert take_pending() == []


# --- session lifecycle promotion / drop ------------------------------------


def test_commit_promotes_pending_events_to_committed_bucket() -> None:
    """Replays the `after_commit` hook: pending events should move into
    the committed bucket, ready for the middleware to dispatch."""
    queue_event("site", "create", 1, None, {"name": "HQ"}, user_id=None)
    queue_event("site", "update", 1, {"name": "HQ"}, {"name": "HQ2"}, user_id=None)
    # Before commit: pending has events, committed bucket is empty.
    assert take_committed() == []
    _promote_pending_to_committed()
    # After commit: pending drained, committed bucket holds both events.
    assert take_pending() == []
    committed = take_committed()
    assert [c.event_name for c in committed] == ["site.create", "site.update"]


def test_rollback_drops_pending_without_touching_committed() -> None:
    """Codex P1 on PR #62: the CSV import dry-run flushes (queues events)
    and then rolls back. The rollback must wipe pending so subscribers
    never see those mutations."""
    # First commit some events so the committed bucket isn't empty.
    queue_event("site", "create", 1, None, {"name": "HQ"}, user_id=None)
    _promote_pending_to_committed()
    # Then flush some more — they belong to a transaction we're about to roll back.
    queue_event("port", "update", 7, {"label": "old"}, {"label": "new"}, user_id=None)
    _drop_pending()
    assert take_pending() == []
    # The previously-committed events survive the rollback.
    committed = take_committed()
    assert len(committed) == 1
    assert committed[0].event_name == "site.create"


def test_take_committed_returns_empty_when_no_commit_happened() -> None:
    queue_event("port", "create", 5, None, {"id": 5}, user_id=None)
    # Without calling _promote_pending_to_committed, the committed bucket is
    # untouched — so the middleware would dispatch nothing.
    assert take_committed() == []


# --- bounded dispatch concurrency (Fix #5) ---------------------------------


@pytest.mark.asyncio
async def test_deliver_one_bounded_never_exceeds_the_semaphore_limit() -> None:
    """`_dispatch_events` used to `asyncio.gather` one `_deliver_one` task
    per event x webhook pair with no cap — each opens its own DB session,
    so a mutation with many subscribed webhooks (or a bulk import queuing
    many events) could saturate the pool. `_deliver_one_bounded` gates
    real dispatch through a semaphore; this pins that the gate actually
    holds under concurrent load, independent of the HTTP/DB internals of
    `_deliver_one` (mocked out here)."""
    concurrent = 0
    max_concurrent = 0
    lock = asyncio.Lock()

    async def fake_deliver_one(webhook_id, url, secret, ev):
        nonlocal concurrent, max_concurrent
        async with lock:
            concurrent += 1
            max_concurrent = max(max_concurrent, concurrent)
        await asyncio.sleep(0.01)
        async with lock:
            concurrent -= 1

    ev = WebhookEvent(
        entity="port", action="update", entity_id=1, before=None, after=None, user_id=None
    )
    semaphore = asyncio.Semaphore(2)

    with patch.object(webhooks_module, "_deliver_one", fake_deliver_one):
        await asyncio.gather(
            *[
                webhooks_module._deliver_one_bounded(semaphore, i, "http://x", "s", ev)
                for i in range(10)
            ]
        )

    assert max_concurrent <= 2
