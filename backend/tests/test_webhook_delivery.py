"""Delivery-path tests for the webhook dispatcher.

`tests/test_webhooks.py` covers the pure helpers (matching, signing,
ContextVar queue); this file exercises the HTTP + persistence side of
`_deliver_one`, the `_dispatch_events` fan-out and `send_test_event`,
with `safe_post` and `SessionLocal` replaced by fakes — no network, no DB.
"""

from __future__ import annotations

import json
import socket
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from sqlalchemy.sql.dml import Delete, Update

import app.services.webhooks as webhooks
from app.models.webhook import WebhookDelivery
from app.services.webhooks import WebhookEvent, _deliver_one, _dispatch_events, send_test_event, sign_body


def _event(entity: str = "site", action: str = "create") -> WebhookEvent:
    return WebhookEvent(
        entity=entity,
        action=action,
        entity_id=1,
        before=None,
        after={"name": "HQ"},
        user_id=7,
    )


class _FakeResult:
    def __init__(self, rows: list | None = None) -> None:
        self._rows = rows or []

    def scalars(self) -> SimpleNamespace:
        rows = list(self._rows)
        return SimpleNamespace(all=lambda: rows)


class _FakeDb:
    """Just enough of an AsyncSession to satisfy the dispatcher."""

    def __init__(self, webhooks_rows: list | None = None, fail_commit: bool = False) -> None:
        self.webhooks_rows = webhooks_rows or []
        self.fail_commit = fail_commit
        self.added: list = []
        self.executed: list = []
        self.commits = 0

    async def __aenter__(self) -> _FakeDb:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def execute(self, stmt: object) -> _FakeResult:
        self.executed.append(stmt)
        return _FakeResult(self.webhooks_rows)

    async def commit(self) -> None:
        if self.fail_commit:
            raise RuntimeError("db down")
        self.commits += 1

    async def refresh(self, obj: object) -> None:
        obj.id = 123
        obj.created_at = datetime.now(UTC)


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch) -> _FakeDb:
    db = _FakeDb()
    monkeypatch.setattr(webhooks, "SessionLocal", lambda: db)
    return db


class _SafePostRecorder:
    """Replaces `safe_post` inside the webhooks module; records each call
    and returns / raises what the test configured."""

    def __init__(self, response: httpx.Response | None = None, raises: Exception | None = None) -> None:
        self.response = response
        self.raises = raises
        self.calls: list[dict] = []

    async def __call__(self, url: str, **kwargs) -> httpx.Response:
        self.calls.append({"url": url, **kwargs})
        if self.raises is not None:
            raise self.raises
        assert self.response is not None
        return self.response


# --- _deliver_one ------------------------------------------------------------


@pytest.mark.asyncio
async def test_deliver_one_success_persists_row_and_signs_body(
    fake_db: _FakeDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _SafePostRecorder(response=httpx.Response(200, content=b"ok"))
    monkeypatch.setattr(webhooks, "safe_post", recorder)

    ev = _event()
    delivery = await _deliver_one(1, "https://hooks.example/x", "s3cret", ev)

    assert delivery.success is True
    assert delivery.status_code == 200
    assert delivery.error is None
    assert delivery.id == 123  # refreshed after commit
    # The exact bytes that went on the wire must match the signature header.
    call = recorder.calls[0]
    assert call["url"] == "https://hooks.example/x"
    assert call["headers"]["X-Netforge-Signature"] == sign_body("s3cret", call["content"])
    assert call["headers"]["X-Netforge-Event"] == "site.create"
    assert json.loads(call["content"])["event"] == "site.create"
    # Row persisted + aggregate counters updated in one transaction.
    assert delivery in fake_db.added
    assert any(isinstance(s, Update) for s in fake_db.executed)
    assert fake_db.commits == 1


@pytest.mark.asyncio
async def test_deliver_one_http_error_is_recorded_and_not_retried(
    fake_db: _FakeDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Webhooks are best-effort: a failing endpoint yields exactly ONE
    attempt whose failure lands in the delivery log — no retry loop."""
    recorder = _SafePostRecorder(response=httpx.Response(500, content=b"boom"))
    monkeypatch.setattr(webhooks, "safe_post", recorder)

    delivery = await _deliver_one(1, "https://hooks.example/x", "s", _event())

    assert delivery.success is False
    assert delivery.status_code == 500
    assert delivery.error is not None and delivery.error.startswith("HTTP 500")
    assert len(recorder.calls) == 1  # single attempt, by design
    assert delivery in fake_db.added


@pytest.mark.asyncio
async def test_deliver_one_timeout_is_recorded(
    fake_db: _FakeDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _SafePostRecorder(raises=httpx.ReadTimeout("too slow"))
    monkeypatch.setattr(webhooks, "safe_post", recorder)

    delivery = await _deliver_one(1, "https://hooks.example/x", "s", _event())

    assert delivery.success is False
    assert delivery.status_code == 0
    assert "timeout" in (delivery.error or "")


@pytest.mark.asyncio
async def test_deliver_one_ssrf_refusal_short_circuits_http(fake_db: _FakeDb) -> None:
    """End-to-end through the REAL `safe_post`: a hostname resolving to
    RFC1918 space is refused before any connection and the refusal is
    persisted in the delivery row for the operator to see."""

    def _resolve_private(_host: str, *_a, **_kw):
        return [(0, 0, 0, "", ("10.1.2.3", 0))]

    with patch("app.utils.ssrf.socket.getaddrinfo", side_effect=_resolve_private):
        delivery = await _deliver_one(1, "https://internal.example.com/hook", "s", _event())

    assert delivery.success is False
    assert delivery.status_code == 0
    assert "UnsafeOutboundURL" in (delivery.error or "")
    assert "not globally routable" in (delivery.error or "")


@pytest.mark.asyncio
async def test_deliver_one_dns_failure_is_recorded(fake_db: _FakeDb) -> None:
    def _resolve_fail(host: str, *_a, **_kw):
        raise socket.gaierror(f"no fixture for {host!r}")

    with patch("app.utils.ssrf.socket.getaddrinfo", side_effect=_resolve_fail):
        delivery = await _deliver_one(1, "https://gone.example/hook", "s", _event())

    assert delivery.success is False
    assert "DNS lookup failed" in (delivery.error or "")


# --- _dispatch_events fan-out -------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_events_fans_out_to_matching_webhooks_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        SimpleNamespace(id=1, url="https://a.example/", secret="sa", events=["port.*"], enabled=True),
        SimpleNamespace(id=2, url="https://b.example/", secret="sb", events=["site.create"], enabled=True),
    ]
    db = _FakeDb(webhooks_rows=rows)
    monkeypatch.setattr(webhooks, "SessionLocal", lambda: db)
    # Skip the lazy retention sweep — exercised separately.
    monkeypatch.setattr(webhooks, "_last_cleanup_at", datetime.now(UTC))

    delivered: list[tuple[int, str]] = []

    async def _fake_deliver(webhook_id: int, _url: str, _secret: str, ev: WebhookEvent) -> None:
        delivered.append((webhook_id, ev.event_name))

    monkeypatch.setattr(webhooks, "_deliver_one", _fake_deliver)

    await _dispatch_events([_event("port", "update"), _event("vlan", "delete")])

    # port.update matches webhook 1 only; vlan.delete matches nothing.
    assert delivered == [(1, "port.update")]


@pytest.mark.asyncio
async def test_dispatch_events_runs_lazy_delivery_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        SimpleNamespace(id=1, url="https://a.example/", secret="sa", events=["*"], enabled=True),
    ]
    db = _FakeDb(webhooks_rows=rows)
    monkeypatch.setattr(webhooks, "SessionLocal", lambda: db)
    monkeypatch.setattr(webhooks, "_last_cleanup_at", None)

    async def _fake_deliver(*_args: object) -> None:
        return None

    monkeypatch.setattr(webhooks, "_deliver_one", _fake_deliver)

    await _dispatch_events([_event()])

    assert any(isinstance(s, Delete) for s in db.executed)


# --- send_test_event ----------------------------------------------------------


@pytest.mark.asyncio
async def test_send_test_event_returns_the_persisted_delivery(
    fake_db: _FakeDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _SafePostRecorder(response=httpx.Response(204, content=b""))
    monkeypatch.setattr(webhooks, "safe_post", recorder)

    hook = SimpleNamespace(id=5, url="https://hooks.example/t", secret="s")
    delivery = await send_test_event(hook)

    assert isinstance(delivery, WebhookDelivery)
    assert delivery.event == "webhook.test"
    assert delivery.success is True
    assert delivery.id == 123


@pytest.mark.asyncio
async def test_send_test_event_survives_persist_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: the old implementation re-queried the freshly-inserted
    row with `scalar_one()` — when persisting failed, the endpoint crashed
    with a 500 instead of reporting the (possibly successful) POST."""
    db = _FakeDb(fail_commit=True)
    monkeypatch.setattr(webhooks, "SessionLocal", lambda: db)
    recorder = _SafePostRecorder(response=httpx.Response(200, content=b"ok"))
    monkeypatch.setattr(webhooks, "safe_post", recorder)

    hook = SimpleNamespace(id=5, url="https://hooks.example/t", secret="s")
    delivery = await send_test_event(hook)

    # Synthetic, never-persisted row — but it still carries the outcome.
    assert delivery.id == 0
    assert delivery.success is True
    assert delivery.status_code == 200
    assert delivery.created_at is not None
