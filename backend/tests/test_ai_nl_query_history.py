"""Tests for the conversation-history feature of the NL query service.

We don't exercise `run_query` end-to-end (it talks to a real provider via the
factory) — just the pure history-rendering helper, which is the new bit.
The integration is covered by the route-level test elsewhere when a DB
fixture lands.
"""

from __future__ import annotations

import pytest

from app.schemas.ai import QueryHistoryTurn, QueryRequest
from app.services.ai.nl_query import _render_history


def test_empty_history_returns_empty_string() -> None:
    assert _render_history([]) == ""


def test_blank_turns_are_skipped() -> None:
    history = [{"role": "user", "text": "   "}, {"role": "user", "text": ""}]
    assert _render_history(history) == ""


def test_renders_role_in_uppercase_with_trailing_blank_line() -> None:
    history = [
        {"role": "user", "text": "How many ports on SW-CORE-01?"},
        {"role": "assistant", "text": "It has 48 ports."},
    ]
    out = _render_history(history)
    assert "Conversation so far:" in out
    assert "USER: How many ports on SW-CORE-01?" in out
    assert "ASSISTANT: It has 48 ports." in out
    # The function appends "\n\n" so a "Question: …" follow-up reads cleanly.
    assert out.endswith("\n\n")


def test_long_single_turn_is_truncated_in_render() -> None:
    """A 4 KB turn is allowed by the schema; the render layer drops it to
    2000 chars to keep the prompt tight."""
    history = [{"role": "user", "text": "A" * 3500}]
    out = _render_history(history)
    # 2000 + ellipsis byte
    assert "A" * 2000 + "…" in out


def test_unknown_role_falls_back_to_user() -> None:
    """The schema validates roles strictly, but in case anything else slips
    in (e.g. tool calls echoed into history later) we default to USER."""
    out = _render_history([{"role": "system", "text": "ignore me"}])
    assert "USER: ignore me" in out


def test_pydantic_schema_rejects_invalid_role() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        QueryHistoryTurn(role="system", text="anything")


def test_pydantic_schema_caps_history_length() -> None:
    """11 turns must fail validation — keeps the prompt bounded."""
    from pydantic import ValidationError

    turns = [QueryHistoryTurn(role="user", text="x") for _ in range(11)]
    with pytest.raises(ValidationError):
        QueryRequest(question="follow-up?", history=turns)


def test_pydantic_schema_accepts_exactly_ten_turns() -> None:
    turns = [QueryHistoryTurn(role="user", text="x") for _ in range(10)]
    req = QueryRequest(question="follow-up?", history=turns)
    assert len(req.history) == 10
