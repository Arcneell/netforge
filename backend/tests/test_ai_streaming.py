"""Tests for the streaming Ask AI pipeline.

We test:
- The streaming nl_query generator with a fake provider (service layer).
- The provider type contract — `StreamDelta` / `StreamDone` consumption.
- The route layer (SSE framing) end-to-end via the ASGI app in
  `test_sse_endpoint_emits_frames` / `test_sse_endpoint_emits_error_frame`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.auth.dependencies import get_current_user
from app.db import get_session as get_db_session
from app.main import app
from app.models.user import User, UserRole
from app.services.ai import nl_query
from app.services.ai.types import (
    AIProviderError,
    StreamDelta,
    StreamDone,
    TokenUsage,
)


def _scalars(rows: list) -> MagicMock:
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=rows)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    return result


def _mock_db_for_query() -> AsyncMock:
    """The cached context builder calls execute() once per tracked table.
    For these tests we only care about the streaming path — return empty
    rowsets so the snapshot JSON ends up tiny."""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalars([]))
    db.add = MagicMock()
    db.commit = AsyncMock()
    return db


def _fake_provider(deltas: list[str], usage: TokenUsage | None = None) -> SimpleNamespace:
    usage = usage or TokenUsage(prompt_tokens=42, completion_tokens=21)

    async def stream_call(**_kwargs):
        full = ""
        for d in deltas:
            full += d
            yield StreamDelta(text=d)
        yield StreamDone(text=full, usage=usage)

    return SimpleNamespace(name="anthropic", model="claude-test", stream_call=stream_call)


@pytest.mark.asyncio
async def test_lite_snapshot_strips_freetext_and_replaces_lists_with_counts() -> None:
    """Codex P1 on PR #58 worried that `lite_context` was advertised on the
    schema but only honoured by the streaming path. The shared
    `_lite_snapshot` helper is what both paths call; this pins the shape
    it returns so a refactor can't silently re-introduce free-text fields
    into the lite payload."""
    full = {
        "sites": [{"id": 1, "name": "HQ", "code": "PAR", "address": "10 rue X"}],
        "rooms": [{"id": 1, "site_id": 1, "code": "R-101", "description": "MDF"}],
        "switches": [
            {
                "id": 1,
                "name": "SW-CORE",
                "room_id": 1,
                "site_id": 1,
                "vendor": "Cisco",
                "model": "9300",
                "description": "main core",
            }
        ],
        "vlans": [{"id": 1, "vlan_id": 10, "name": "users", "color": "#fff"}],
        "subnets": [
            {
                "id": 1,
                "cidr": "10.0.0.0/24",
                "vlan_id": 1,
                "site_id": 1,
                "description": "user VLAN",
            }
        ],
        "devices": [{"id": 1, "name": "srv-01", "serial": "ABC123"}],
        "ports": [{"id": 1, "label": "Gi1/0/1", "notes": "uplink"}],
        "existing_links": [{"port_a_id": 1, "port_b_id": 2}],
    }
    lite = nl_query._lite_snapshot(full)
    # Free-text fields are stripped from every entity.
    assert "address" not in lite["sites"][0]
    assert "description" not in lite["rooms"][0]
    assert "vendor" not in lite["switches"][0] and "description" not in lite["switches"][0]
    assert "color" not in lite["vlans"][0]
    assert "description" not in lite["subnets"][0]
    # High-cardinality lists collapse to counts so the prompt stays bounded.
    assert lite["device_count"] == 1
    assert lite["port_count"] == 1
    assert lite["existing_link_count"] == 1
    # IDs survive so the model can still reason about structure.
    assert lite["switches"][0]["id"] == 1
    assert lite["switches"][0]["room_id"] == 1


@pytest.mark.asyncio
async def test_run_query_honours_lite_context_on_non_streaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex P1 on PR #58: `lite_context` on `/query` (non-stream) was
    advertised on the schema but ignored — only `/query/stream` applied it,
    so an operator who flipped the toggle on the non-streaming endpoint
    silently leaked free-text fields to the model. This test pins that
    `run_query(lite_context=True)` reaches the provider with the stripped
    snapshot in `cache_prefix`, not the verbose one."""
    captured: dict = {}

    class _FakeCompletion:
        usage = SimpleNamespace(prompt_tokens=1, completion_tokens=1)
        tool_call = SimpleNamespace(input={"answer": "ok", "referenced_entities": []})

    async def fake_call(*, system, prompt, cache_prefix, tools, max_tokens, temperature):
        captured["cache_prefix"] = cache_prefix
        return _FakeCompletion()

    fake_provider = SimpleNamespace(name="anthropic", model="t", call=fake_call)
    monkeypatch.setattr(nl_query, "get_provider", lambda: fake_provider)
    monkeypatch.setattr(
        nl_query,
        "build_topology_context_cached",
        AsyncMock(
            return_value=(
                {
                    "sites": [{"id": 1, "name": "HQ", "code": "PAR", "address": "secret"}],
                    "rooms": [],
                    "switches": [],
                    "vlans": [],
                    "subnets": [],
                    "devices": [{"id": 1, "name": "srv", "serial": "SECRET"}],
                    "ports": [],
                    "existing_links": [],
                },
                False,
            )
        ),
    )

    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()

    await nl_query.run_query(
        db, user_id=1, question="ping?", lite_context=True
    )
    # Free-text "address" and "serial" must not appear in what the provider sees.
    assert "secret" not in captured["cache_prefix"]
    assert "SECRET" not in captured["cache_prefix"]
    # The count-replacement signature for high-cardinality tables.
    assert "device_count" in captured["cache_prefix"]


@pytest.mark.asyncio
async def test_streaming_emits_delta_then_done(monkeypatch: pytest.MonkeyPatch) -> None:
    """Happy path: deltas are forwarded in order, then a single `done`
    frame closes the stream."""
    monkeypatch.setattr(
        nl_query, "get_provider", lambda: _fake_provider(["Hello", " world"])
    )
    monkeypatch.setattr(
        nl_query,
        "build_topology_context_cached",
        AsyncMock(return_value=({"sites": []}, False)),
    )

    db = _mock_db_for_query()
    events = []
    async for ev in nl_query.run_query_streaming(
        db, user_id=1, question="ping?", history=[], language_instruction=None
    ):
        events.append(ev)

    # 2 delta frames + 1 done frame
    assert [e[0] for e in events] == ["delta", "delta", "done"]
    assert events[0][1]["text"] == "Hello"
    assert events[1][1]["text"] == " world"
    done = events[2][1]
    assert done["answer"] == "Hello world"
    assert done["prompt_tokens"] == 42
    assert done["completion_tokens"] == 21


@pytest.mark.asyncio
async def test_streaming_emits_error_frame_on_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An `AIProviderError` mid-stream surfaces as an `error` SSE frame and
    does NOT emit a final `done` (the partial answer is whatever was streamed
    up to that point)."""

    async def stream_call(**_kwargs):
        yield StreamDelta(text="partial")
        raise AIProviderError("boom")

    fake = SimpleNamespace(name="anthropic", model="claude-test", stream_call=stream_call)
    monkeypatch.setattr(nl_query, "get_provider", lambda: fake)
    monkeypatch.setattr(
        nl_query,
        "build_topology_context_cached",
        AsyncMock(return_value=({"sites": []}, False)),
    )

    db = _mock_db_for_query()
    events = []
    async for ev in nl_query.run_query_streaming(
        db, user_id=1, question="ping?", history=[], language_instruction=None
    ):
        events.append(ev)

    kinds = [e[0] for e in events]
    assert "error" in kinds
    assert "done" not in kinds
    err_payload = next(e[1] for e in events if e[0] == "error")
    assert "boom" in err_payload["message"]


@pytest.mark.asyncio
async def test_streaming_logs_run_with_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even when no delta is emitted (e.g. provider replies with empty text),
    the run log is still written so the Usage dashboard accounts for the call."""
    monkeypatch.setattr(nl_query, "get_provider", lambda: _fake_provider([]))
    monkeypatch.setattr(
        nl_query,
        "build_topology_context_cached",
        AsyncMock(return_value=({"sites": []}, False)),
    )

    db = _mock_db_for_query()
    [_ async for _ in nl_query.run_query_streaming(
        db, user_id=1, question="ping?", history=[], language_instruction=None
    )]
    # db.add called once for the AIRunLog row.
    assert db.add.call_count == 1
    db.commit.assert_awaited()


# --- Route layer: SSE framing over the real ASGI app -----------------------


def _admin_user() -> User:
    return User(
        id=7, provider="github", subject="a",
        email="a@example.com", display_name="A", role=UserRole.admin,
    )


@pytest_asyncio.fixture
async def sse_client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    """ASGI client with AI enabled, an admin user, the rate limiter and the
    DB dependency stubbed out. Each test monkeypatches `run_query_streaming`
    to control the event sequence the route has to frame."""
    # AI master flag on (so _require_ai_enabled passes) without touching env.
    monkeypatch.setattr(
        "app.routers.ai.get_settings",
        lambda: SimpleNamespace(ai_enabled=True),
    )
    # Don't consume the real per-user rate-limit window.
    monkeypatch.setattr("app.routers.ai.check_and_consume", lambda _user_id: None)

    # get_current_user feeds both the explicit param and the admin role guard.
    app.dependency_overrides[get_current_user] = _admin_user

    async def _fake_db() -> AsyncIterator:
        # conversation_id is omitted in these tests, so the route never
        # actually touches this session — a stub keeps get_session from
        # opening a real connection.
        yield AsyncMock()

    app.dependency_overrides[get_db_session] = _fake_db

    # Use a dedicated client IP so our POSTs land in their own write
    # rate-limit bucket — the suite's other write tests share the default
    # 127.0.0.1 bucket and run right under the per-window cap.
    transport = ASGITransport(app=app, client=("10.42.0.1", 5555))
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


def _parse_sse(body: str) -> list[tuple[str, str]]:
    """Parse an SSE body into (event, data) pairs, ignoring `:` comment
    preamble frames."""
    frames: list[tuple[str, str]] = []
    for block in body.split("\n\n"):
        block = block.strip()
        if not block or block.startswith(":"):
            continue
        event = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = line[len("data:"):].strip()
        frames.append((event, data))
    return frames


@pytest.mark.asyncio
async def test_sse_endpoint_emits_frames(
    sse_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The route must set text/event-stream + no-buffering headers and frame
    each (event, data) pair from run_query_streaming as a proper SSE frame,
    deltas before the final done."""
    import json

    async def _fake_stream(*_args, **_kwargs):
        yield ("delta", {"text": "Hello"})
        yield ("delta", {"text": " world"})
        yield ("done", {"answer": "Hello world", "prompt_tokens": 1, "completion_tokens": 1})

    monkeypatch.setattr("app.routers.ai.run_query_streaming", _fake_stream)

    resp = await sse_client.post("/api/ai/query/stream", json={"question": "ping?"})

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    # SSE must not be buffered by intermediaries.
    assert resp.headers.get("x-accel-buffering") == "no"
    assert resp.headers.get("cache-control") == "no-cache"

    frames = _parse_sse(resp.text)
    assert [name for name, _ in frames] == ["delta", "delta", "done"]
    assert json.loads(frames[0][1])["text"] == "Hello"
    assert json.loads(frames[1][1])["text"] == " world"
    done = json.loads(frames[2][1])
    assert done["answer"] == "Hello world"


@pytest.mark.asyncio
async def test_sse_endpoint_emits_error_frame(
    sse_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the generator blows up mid-stream the route catches it and frames a
    terminal `error` event instead of letting the connection hang or 500."""
    import json

    async def _boom_stream(*_args, **_kwargs):
        yield ("delta", {"text": "partial"})
        raise RuntimeError("kaboom")

    monkeypatch.setattr("app.routers.ai.run_query_streaming", _boom_stream)

    resp = await sse_client.post("/api/ai/query/stream", json={"question": "ping?"})

    assert resp.status_code == 200
    frames = _parse_sse(resp.text)
    names = [name for name, _ in frames]
    assert names == ["delta", "error"]
    assert "done" not in names
    assert "kaboom" in json.loads(frames[1][1])["message"]
