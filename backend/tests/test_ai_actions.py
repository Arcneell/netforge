"""Tests for the NL-to-action draft / apply pipeline."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.ai import actions as svc

# --- Pure payload validators -----------------------------------------------


def test_validate_create_site_requires_code_and_name() -> None:
    assert isinstance(svc._validate_payload("create_site", {"name": "Paris"}), str)
    assert isinstance(svc._validate_payload("create_site", {"code": "PAR"}), str)


def test_validate_create_site_uppercases_code() -> None:
    out = svc._validate_payload("create_site", {"code": "par", "name": "Paris", "address": " "})
    assert isinstance(out, dict)
    assert out["code"] == "PAR"
    # Blank address coerces to None.
    assert out["address"] is None


def test_validate_create_room_uppercases_site_code() -> None:
    out = svc._validate_payload(
        "create_room", {"site_code": "par", "code": "R-101", "description": "DC"}
    )
    assert out["site_code"] == "PAR"


def test_validate_create_vlan_bounds() -> None:
    assert isinstance(svc._validate_payload("create_vlan", {"vlan_id": 0, "name": "x"}), str)
    assert isinstance(svc._validate_payload("create_vlan", {"vlan_id": 5000, "name": "x"}), str)
    ok = svc._validate_payload("create_vlan", {"vlan_id": 50, "name": "IoT"})
    assert ok == {"vlan_id": 50, "name": "IoT", "description": None, "color": None}


def test_validate_create_subnet_minimum() -> None:
    """Only cidr + site_code are mandatory; gateway/vlan_id stay optional."""
    out = svc._validate_payload(
        "create_subnet",
        {"cidr": "10.0.0.0/24", "site_code": "par", "vlan_id": "50"},
    )
    assert isinstance(out, dict)
    assert out == {"cidr": "10.0.0.0/24", "site_code": "PAR", "vlan_id": 50}


def test_validate_unknown_intent() -> None:
    assert isinstance(svc._validate_payload("nuke_everything", {}), str)


# --- Appliers ---------------------------------------------------------------


def _scalar_result(value) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=value)
    return r


def _mock_db(scalar_results: list) -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_scalar_result(v) for v in scalar_results])
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_apply_create_site_rejects_duplicate_code() -> None:
    db = _mock_db([SimpleNamespace(id=1, code="PAR")])  # already exists
    with pytest.raises(ValueError):
        await svc._apply_create_site(db, {"code": "PAR", "name": "Paris", "address": None})


@pytest.mark.asyncio
async def test_apply_create_room_requires_existing_site() -> None:
    db = _mock_db([None])  # site lookup empty
    with pytest.raises(ValueError):
        await svc._apply_create_room(
            db, {"site_code": "ZZ", "code": "R-1", "description": None}
        )


@pytest.mark.asyncio
async def test_apply_create_vlan_rejects_duplicate_id() -> None:
    db = _mock_db([SimpleNamespace(id=1, vlan_id=50)])
    with pytest.raises(ValueError):
        await svc._apply_create_vlan(
            db, {"vlan_id": 50, "name": "IoT", "description": None, "color": None}
        )


@pytest.mark.asyncio
async def test_apply_create_subnet_rejects_unknown_vrf_id() -> None:
    """LOW audit fix: `vrf_id` comes straight from the LLM, unverified. A
    stale snapshot or a hallucinated id must fail with a clean `ValueError`
    (like the site_code / vlan_id checks above it) instead of surfacing as
    a raw FK-violation IntegrityError from the INSERT."""
    site = SimpleNamespace(id=1)
    db = AsyncMock()
    # 1st execute(): site lookup succeeds. Then `db.get(Vrf, vrf_id)` is
    # called (not `execute`) and returns None — unknown vrf.
    db.execute = AsyncMock(side_effect=[_scalar_result(site)])
    db.get = AsyncMock(return_value=None)
    with pytest.raises(ValueError, match="VRF"):
        await svc._apply_create_subnet(
            db, {"cidr": "10.0.0.0/24", "site_code": "PAR", "vrf_id": 999}
        )


@pytest.mark.asyncio
async def test_apply_create_subnet_accepts_known_vrf_id() -> None:
    site = SimpleNamespace(id=1)
    vrf = SimpleNamespace(id=999)
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_scalar_result(site)])
    db.get = AsyncMock(return_value=vrf)
    db.add = MagicMock()
    db.flush = AsyncMock()
    pointer = await svc._apply_create_subnet(
        db, {"cidr": "10.0.0.0/24", "site_code": "PAR", "vrf_id": 999}
    )
    assert pointer.startswith("subnet:")
    db.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_apply_create_subnet_requires_existing_site_and_vlan() -> None:
    # Site lookup hits nothing.
    db = _mock_db([None])
    with pytest.raises(ValueError):
        await svc._apply_create_subnet(
            db, {"cidr": "10.0.0.0/24", "site_code": "ZZ"}
        )

    # Site OK but vlan_id is unknown.
    site = SimpleNamespace(id=1)
    db = _mock_db([site, None])
    with pytest.raises(ValueError):
        await svc._apply_create_subnet(
            db, {"cidr": "10.0.0.0/24", "site_code": "PAR", "vlan_id": 999}
        )


# --- Apply / reject lifecycle ----------------------------------------------


@pytest.mark.asyncio
async def test_apply_draft_locks_the_row_for_update() -> None:
    """LOW audit fix: without a row lock, two concurrent apply requests for
    the same draft can both read `status=pending` before either commits and
    both proceed — a TOCTOU double-apply. The fetch must take
    `SELECT ... FOR UPDATE` via `with_for_update=True`."""
    draft = SimpleNamespace(
        id=1,
        intent="create_vlan",
        payload={"vlan_id": 50, "name": "IoT", "description": None, "color": None},
        status=svc.AIActionDraftStatus.applied,  # already resolved -> short-circuits cleanly
        error_code=None,
        error_message=None,
        applied_at=None,
        applied_by_user_id=None,
        applied_resource=None,
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=draft)
    with pytest.raises(ValueError):
        await svc.apply_draft(db, draft_id=1, user_id=99)
    db.get.assert_awaited_once_with(svc.AIActionDraft, 1, with_for_update=True)


@pytest.mark.asyncio
async def test_apply_draft_marks_failed_on_inner_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the per-intent applier raises, the draft must transition to
    `failed` with the error code+message captured."""
    draft = SimpleNamespace(
        id=1,
        intent="create_vlan",
        payload={"vlan_id": 50, "name": "IoT", "description": None, "color": None},
        status=svc.AIActionDraftStatus.pending,
        error_code=None,
        error_message=None,
        applied_at=None,
        applied_by_user_id=None,
        applied_resource=None,
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=draft)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    async def boom(*a, **k):
        raise ValueError("boom")

    monkeypatch.setattr(svc, "_apply_create_vlan", boom)

    with pytest.raises(ValueError):
        await svc.apply_draft(db, draft_id=1, user_id=99)
    assert draft.status == svc.AIActionDraftStatus.failed
    assert draft.error_code == "DRAFT_INVALID"
    assert "boom" in (draft.error_message or "")


@pytest.mark.asyncio
async def test_apply_draft_classifies_integrity_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A subnet-overlap IntegrityError should map to SUBNET_OVERLAP + a
    friendly English message that the frontend i18n keys off."""
    from sqlalchemy.exc import IntegrityError

    draft = SimpleNamespace(
        id=1,
        intent="create_subnet",
        payload={"cidr": "10.10.10.0/24", "site_code": "PAR-DC1"},
        status=svc.AIActionDraftStatus.pending,
        error_code=None,
        error_message=None,
        applied_at=None,
        applied_by_user_id=None,
        applied_resource=None,
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=draft)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    async def overlap(*a, **k):
        raise IntegrityError(
            "INSERT INTO subnets ...",
            params=None,
            orig=Exception(
                "ExclusionViolationError: conflicting key value violates "
                "exclusion constraint 'subnets_no_overlap_global'"
            ),
        )

    monkeypatch.setattr(svc, "_apply_create_subnet", overlap)

    with pytest.raises(IntegrityError):
        await svc.apply_draft(db, draft_id=1, user_id=99)
    assert draft.status == svc.AIActionDraftStatus.failed
    assert draft.error_code == "SUBNET_OVERLAP"
    assert draft.error_message == "This CIDR overlaps an existing subnet."


@pytest.mark.asyncio
async def test_apply_draft_rejects_already_resolved() -> None:
    draft = SimpleNamespace(
        id=1,
        intent="create_vlan",
        payload={},
        status=svc.AIActionDraftStatus.applied,
        error_code=None,
        error_message=None,
        applied_at=None,
        applied_by_user_id=None,
        applied_resource=None,
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=draft)
    with pytest.raises(ValueError):
        await svc.apply_draft(db, draft_id=1, user_id=99)


@pytest.mark.asyncio
async def test_reject_draft_marks_rejected() -> None:
    draft = SimpleNamespace(
        id=1,
        status=svc.AIActionDraftStatus.pending,
        applied_at=None,
        applied_by_user_id=None,
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=draft)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    out = await svc.reject_draft(db, draft_id=1, user_id=42)
    assert out.status == svc.AIActionDraftStatus.rejected
    assert out.applied_by_user_id == 42


# --- Route error mapping ----------------------------------------------------


@pytest.mark.asyncio
async def test_apply_route_maps_integrity_error_to_409(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression for the 502-on-apply bug: when the inner applier trips a
    DB constraint (e.g. `subnets_no_overlap` GiST), the route used to leak
    a bare 500 (or 502 behind nginx) with no detail. Now: 409 with the
    constraint message in `detail`."""
    from fastapi import HTTPException
    from sqlalchemy.exc import IntegrityError

    from app.routers.ai import drafts as ai_route

    # `_require_drafts_enabled` reads settings — patch it to a no-op so we
    # can drive the route handler in isolation.
    monkeypatch.setattr(ai_route, "_require_drafts_enabled", lambda: None)

    async def boom(*_a, **_kw):
        raise IntegrityError("INSERT ...", params=None, orig=Exception("subnet overlaps 10.0.0.0/24"))

    monkeypatch.setattr(ai_route, "apply_draft", boom)

    user = SimpleNamespace(id=1)
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await ai_route.apply_draft_route(draft_id=1, user=user, db=db)
    assert exc.value.status_code == 409
    assert "overlap" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_apply_route_maps_unexpected_exception_to_502(monkeypatch: pytest.MonkeyPatch) -> None:
    """Anything that isn't LookupError / ValueError / IntegrityError returns
    a 502 with the stable AI_APPLY_FAILED code and a GENERIC message — the
    exception repr goes to the server log only, because it can leak
    internals (DSNs, file paths, provider payloads) to the client."""
    from fastapi import HTTPException

    from app.routers.ai import drafts as ai_route

    monkeypatch.setattr(ai_route, "_require_drafts_enabled", lambda: None)

    async def boom(*_a, **_kw):
        raise RuntimeError("connection lost mid-commit")

    monkeypatch.setattr(ai_route, "apply_draft", boom)

    user = SimpleNamespace(id=1)
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await ai_route.apply_draft_route(draft_id=1, user=user, db=db)
    assert exc.value.status_code == 502
    detail = str(exc.value.detail)
    assert "AI_APPLY_FAILED" in detail
    # No exception internals in the client-facing payload.
    assert "RuntimeError" not in detail
    assert "connection lost" not in detail
