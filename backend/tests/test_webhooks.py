"""Pure-function tests for the webhook dispatcher.

The HTTP round-trip and DB persistence sides are covered indirectly by the
audit listener / router tests; here we focus on the small bits that are
easy to get wrong: pattern matching, HMAC signing, payload serialisation,
and the request-scoped ContextVar queue.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from app.services.webhooks import (
    WebhookEvent,
    generate_secret,
    matches,
    queue_event,
    set_dispatch_enabled,
    sign_body,
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
    set_dispatch_enabled(True)
    yield
    take_pending()


def test_queue_event_appends_to_request_scoped_bucket() -> None:
    queue_event("site", "create", 1, None, {"name": "HQ"}, user_id=3)
    queue_event("site", "update", 1, {"name": "HQ"}, {"name": "HQ2"}, user_id=3)
    pending = take_pending()
    assert len(pending) == 2
    assert pending[0].event_name == "site.create"
    assert pending[1].event_name == "site.update"
    # Draining clears the queue.
    assert take_pending() == []


def test_queue_event_is_a_noop_when_dispatch_disabled() -> None:
    set_dispatch_enabled(False)
    queue_event("port", "create", 5, None, {"id": 5}, user_id=None)
    assert take_pending() == []
