"""Tests for the streaming Ask AI pipeline.

We test:
- The streaming nl_query generator with a fake provider.
- The provider type contract — `StreamDelta` / `StreamDone` consumption.

The route layer (SSE framing) is exercised via the full app test in
`test_ai_streaming.py::test_sse_endpoint_emits_frames` once a DB fixture
is wired; for now we keep the unit coverage focused on the service layer.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

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
