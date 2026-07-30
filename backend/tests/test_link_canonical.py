"""Verify that the link service swaps endpoints to keep the canonical order
required by the CHECK constraint (port_a_id < port_b_id), plus the helpers
used by the topology UI (by-name create and metadata-only update).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.models.link import Link
from app.models.port import Port
from app.models.switch import Switch
from app.schemas.link import LinkCreate, LinkCreateByName, LinkType, LinkUpdate
from app.services import links as service


@pytest.fixture
def mock_db() -> AsyncMock:
    captured: list[Link] = []

    db = AsyncMock()
    db.get = AsyncMock(return_value=Port(id=1, switch_id=1, number=1))
    # `create_link` runs a SELECT to refuse re-linking a port that's
    # already an endpoint of another link — return an empty result here
    # so the canonical-ordering tests aren't impacted by that guard.
    empty_clash = MagicMock()
    empty_clash.all = MagicMock(return_value=[])
    db.execute = AsyncMock(return_value=empty_clash)
    db.add = MagicMock(side_effect=lambda obj: captured.append(obj))
    db.commit = AsyncMock()

    async def _refresh(obj: Link) -> None:
        if obj.id is None:
            obj.id = 99

    db.refresh = AsyncMock(side_effect=_refresh)
    db._captured = captured  # type: ignore[attr-defined]
    return db


@pytest.mark.asyncio
async def test_link_swaps_reversed_endpoints(mock_db: AsyncMock) -> None:
    link = await service.create_link(
        mock_db, LinkCreate(port_a_id=10, port_b_id=3, link_type=LinkType.fiber)
    )
    assert link.port_a_id == 3
    assert link.port_b_id == 10


@pytest.mark.asyncio
async def test_link_preserves_already_canonical(mock_db: AsyncMock) -> None:
    link = await service.create_link(
        mock_db, LinkCreate(port_a_id=2, port_b_id=8, link_type=LinkType.copper)
    )
    assert link.port_a_id == 2
    assert link.port_b_id == 8


@pytest.mark.asyncio
async def test_create_link_rejects_port_already_linked() -> None:
    """A physical port can only realise one cable, but the DB has no
    constraint that a single port appears in at most one Link. The
    service must refuse to create a second link for a port that's
    already an endpoint of another one — otherwise the AI suggest-links
    accept path (or any direct POST) silently produces a non-physical
    topology where one port is connected to two different peers."""

    class _Row:
        def __init__(self, link_id: int, a: int, b: int) -> None:
            self.id, self.port_a_id, self.port_b_id = link_id, a, b

    # An existing link between ports 5 and 12. Caller now tries to wire
    # port 5 to port 99 — port 5 is already taken.
    clash = MagicMock()
    clash.all = MagicMock(return_value=[_Row(42, 5, 12)])

    db = AsyncMock()
    db.get = AsyncMock(return_value=Port(id=5, switch_id=1, number=1))
    db.execute = AsyncMock(return_value=clash)
    db.add = MagicMock()
    db.commit = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await service.create_link(
            db, LinkCreate(port_a_id=5, port_b_id=99, link_type=LinkType.copper)
        )
    assert exc.value.status_code == 400
    detail = exc.value.detail["error"]
    assert detail["code"] == "PORT_ALREADY_LINKED"
    assert detail["details"]["existing_link_id"] == 42
    # Refusal happens BEFORE we touch the session — no insert leaks
    # through if the guard fires.
    db.add.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_create_link_catches_port_exclusivity_race_as_409_equivalent() -> None:
    """The pre-check above runs outside any lock: two concurrent requests can
    both pass it before either commits, each wiring a shared port to a
    different peer. Migration 0022 adds a `links_validate_port_exclusivity`
    trigger that closes this race at the DB level — its violation must map
    to the same `PORT_ALREADY_LINKED` 400 the non-racing pre-check returns,
    not leak as a raw 500 or a generic integrity error."""
    from sqlalchemy.exc import IntegrityError

    empty_clash = MagicMock()
    empty_clash.all = MagicMock(return_value=[])  # pre-check sees no clash

    db = AsyncMock()
    db.get = AsyncMock(return_value=Port(id=1, switch_id=1, number=1))
    db.execute = AsyncMock(return_value=empty_clash)
    db.add = MagicMock()
    db.rollback = AsyncMock()
    db.commit = AsyncMock(
        side_effect=IntegrityError(
            "INSERT INTO links ...",
            {},
            Exception(
                'port 5 or 99 is already an endpoint of link 42 — violates '
                'unique constraint "links_port_exclusivity"'
            ),
        )
    )

    with pytest.raises(HTTPException) as exc:
        await service.create_link(
            db, LinkCreate(port_a_id=5, port_b_id=99, link_type=LinkType.copper)
        )
    assert exc.value.status_code == 400
    detail = exc.value.detail["error"]
    assert detail["code"] == "PORT_ALREADY_LINKED"
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_link_other_integrity_errors_still_map_generically() -> None:
    """A constraint violation unrelated to the exclusivity trigger (e.g. the
    exact-pair `links_ports_uniq` duplicate) must still go through the
    shared `catch_integrity_errors` mapping, not be swallowed by the new
    trigger-specific branch."""
    from sqlalchemy.exc import IntegrityError

    empty_clash = MagicMock()
    empty_clash.all = MagicMock(return_value=[])

    db = AsyncMock()
    db.get = AsyncMock(return_value=Port(id=1, switch_id=1, number=1))
    db.execute = AsyncMock(return_value=empty_clash)
    db.add = MagicMock()
    db.rollback = AsyncMock()
    db.commit = AsyncMock(
        side_effect=IntegrityError(
            "INSERT INTO links ...",
            {},
            Exception('duplicate key value violates unique constraint "links_ports_uniq"'),
        )
    )

    with pytest.raises(HTTPException) as exc:
        await service.create_link(
            db, LinkCreate(port_a_id=2, port_b_id=8, link_type=LinkType.copper)
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["error"]["code"] == "DUPLICATE_LINK"
    db.rollback.assert_awaited_once()


# --- create_link_by_name --------------------------------------------------- #


def _result(value):
    """Wrap `value` to mimic SQLAlchemy `Result.scalar_one_or_none()`."""
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=value)
    return r


@pytest.mark.asyncio
async def test_create_by_name_resolves_endpoints() -> None:
    """The two (switch_name, port_number) pairs are looked up, the resulting
    ids are passed through `create_link`, and the canonical-order swap still
    applies (here port id 7 < port id 12, so no swap is needed)."""
    sw_a = Switch(id=1, name="SW-A", port_count=24)
    sw_b = Switch(id=2, name="SW-B", port_count=24)
    port_a = Port(id=7, switch_id=1, number=24)
    port_b = Port(id=12, switch_id=2, number=1)

    # No existing link involves either port (the create_link clash guard
    # added in this PR will short-circuit on an empty result).
    empty_clash = MagicMock()
    empty_clash.all = MagicMock(return_value=[])

    db = AsyncMock()
    # Order matches the service: switch_a → port_a → switch_b → port_b → clash check
    db.execute = AsyncMock(side_effect=[
        _result(sw_a),
        _result(port_a),
        _result(sw_b),
        _result(port_b),
        empty_clash,
    ])
    # The downstream create_link does its own port-exists check via db.get.
    db.get = AsyncMock(side_effect=lambda _model, pid: {7: port_a, 12: port_b}[pid])
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "id", 99))

    link = await service.create_link_by_name(
        db,
        LinkCreateByName(
            switch_a="SW-A",
            port_a=24,
            switch_b="SW-B",
            port_b=1,
            link_type=LinkType.fiber,
        ),
    )
    assert link.port_a_id == 7
    assert link.port_b_id == 12
    assert link.link_type == LinkType.fiber


@pytest.mark.asyncio
async def test_create_by_name_unknown_switch_returns_404() -> None:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_result(None))  # switch not found

    with pytest.raises(HTTPException) as exc:
        await service.create_link_by_name(
            db,
            LinkCreateByName(
                switch_a="DOES-NOT-EXIST",
                port_a=1,
                switch_b="SW-B",
                port_b=1,
                link_type=LinkType.copper,
            ),
        )
    assert exc.value.status_code == 404
    assert exc.value.detail["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_create_by_name_unknown_port_returns_404() -> None:
    """The switch exists but the requested port number doesn't — the error
    message identifies which endpoint to fix."""
    sw_a = Switch(id=1, name="SW-A", port_count=24)
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_result(sw_a), _result(None)])

    with pytest.raises(HTTPException) as exc:
        await service.create_link_by_name(
            db,
            LinkCreateByName(
                switch_a="SW-A",
                port_a=999,
                switch_b="SW-B",
                port_b=1,
                link_type=LinkType.copper,
            ),
        )
    assert exc.value.status_code == 404
    assert "SW-A:999" in exc.value.detail["error"]["message"]


# --- update_link ----------------------------------------------------------- #


@pytest.mark.asyncio
async def test_update_link_patches_only_supplied_fields() -> None:
    """`exclude_unset=True` is what makes this a proper PATCH-style PUT:
    unspecified fields keep their existing value, so the UI can save the
    description without clobbering `speed_mbps` etc."""
    existing = Link(
        id=42,
        port_a_id=1,
        port_b_id=2,
        link_type=LinkType.copper,
        speed_mbps=1000,
        description="old",
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=existing)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    updated = await service.update_link(
        db, 42, LinkUpdate(description="new description")
    )
    assert updated.description == "new description"
    assert updated.link_type == LinkType.copper  # untouched
    assert updated.speed_mbps == 1000  # untouched


@pytest.mark.asyncio
async def test_update_link_not_found_raises_404() -> None:
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc:
        await service.update_link(db, 999, LinkUpdate(link_type=LinkType.fiber))
    assert exc.value.status_code == 404
