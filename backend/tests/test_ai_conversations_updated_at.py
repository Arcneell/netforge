"""Tests for the LOW audit fix in `services/ai/conversations.py::append_turn`:
`updated_at` must be bumped on every turn, not only when some other column
happens to be dirtied in the same flush.

Before the fix, a `user` turn on a conversation that ALREADY had a title
(i.e. not the conversation's first turn) touched no column on the `conv`
row itself, so SQLAlchemy's `onupdate=func.now()` never fired. If the LLM
call that follows the user turn then failed, the conversation's
`updated_at` stayed stale — it would not bubble to the top of the
most-recent-first sidebar despite a brand new question having just been
asked.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.ai.conversations import append_turn


def _mock_db(conv: SimpleNamespace) -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.get = AsyncMock(return_value=conv)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_user_turn_bumps_updated_at_even_when_title_already_set() -> None:
    stale = datetime.now(UTC) - timedelta(days=1)
    conv = SimpleNamespace(id=1, title="Existing title", updated_at=stale)
    db = _mock_db(conv)

    await append_turn(db, conversation_id=1, role="user", text="a follow-up question")

    assert conv.updated_at > stale
    # Title is untouched — it was already set, so the auto-title convention
    # doesn't apply to this (non-first) turn.
    assert conv.title == "Existing title"


@pytest.mark.asyncio
async def test_first_user_turn_still_sets_title_and_bumps_updated_at() -> None:
    stale = datetime.now(UTC) - timedelta(days=1)
    conv = SimpleNamespace(id=1, title="", updated_at=stale)
    db = _mock_db(conv)

    await append_turn(db, conversation_id=1, role="user", text="create a VLAN 50")

    assert conv.title == "create a VLAN 50"
    assert conv.updated_at > stale


@pytest.mark.asyncio
async def test_assistant_turn_bumps_updated_at() -> None:
    stale = datetime.now(UTC) - timedelta(days=1)
    conv = SimpleNamespace(id=1, title="Existing title", updated_at=stale)
    db = _mock_db(conv)

    await append_turn(db, conversation_id=1, role="assistant", text="Here's the answer.")

    assert conv.updated_at > stale
