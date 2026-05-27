"""HTTP-level checks on /api/imports and /api/exports.

We verify:
  - imports require admin
  - imports reject unknown entities and oversize uploads
  - dry-run imports return an `applied: false` report without committing
  - exports reject unknown entities (the full streaming path is covered by
    test_crud_auth_guards' auth checks and by the unit tests on csv_export
    once we have a real DB harness)

End-to-end mocking of `db.execute` for both the session lookup AND each
service-level query is brittle; the focused tests above are what matters.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db import get_session as get_db_session
from app.main import app
from app.models.user import Session, User, UserRole


def _viewer() -> User:
    return User(id=1, provider="github", subject="v", email="v@x", role=UserRole.viewer)


def _admin() -> User:
    return User(id=2, provider="github", subject="a", email="a@x", role=UserRole.admin)


def _session() -> Session:
    return Session(
        id="sess", user_id=1,
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(hours=4),
    )


def _install_db(
    user: User | None,
    *,
    execute_returns: list | None = None,
) -> AsyncMock:
    """Wire a mock DB.

    `execute_returns`: optional list of values to return from successive
    `db.execute(...)` calls. The first call is the session lookup; subsequent
    calls hit whatever the endpoint runs (CSV upsert, export query, ...).
    """
    sess_result = MagicMock()
    sess_result.scalar_one_or_none = MagicMock(return_value=_session() if user else None)

    db = AsyncMock()
    if execute_returns is None:
        db.execute = AsyncMock(return_value=sess_result)
    else:
        db.execute = AsyncMock(side_effect=[sess_result, *execute_returns])
    db.get = AsyncMock(return_value=user)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()

    async def _override() -> AsyncIterator:
        yield db

    app.dependency_overrides[get_db_session] = _override
    return db


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


# --- /api/imports ---------------------------------------------------------- #


@pytest.mark.asyncio
async def test_import_rejects_anon(client: AsyncClient) -> None:
    _install_db(user=None)
    r = await client.post(
        "/api/imports/sites",
        files={"file": ("sites.csv", b"code;name\nX;Y\n", "text/csv")},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_import_rejects_viewer(client: AsyncClient) -> None:
    _install_db(user=_viewer())
    r = await client.post(
        "/api/imports/sites",
        files={"file": ("sites.csv", b"code;name\nX;Y\n", "text/csv")},
        cookies={"netforge_session": "sess"},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_import_unknown_entity_returns_400(client: AsyncClient) -> None:
    _install_db(user=_admin())
    r = await client.post(
        "/api/imports/widgets",
        files={"file": ("x.csv", b"a;b\n1;2\n", "text/csv")},
        cookies={"netforge_session": "sess"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "UNKNOWN_ENTITY"


@pytest.mark.asyncio
async def test_import_size_cap_rejects_huge_upload(client: AsyncClient) -> None:
    _install_db(user=_admin())
    too_big = b"a;b\n" + (b"1;2\n" * 3_000_000)  # ~12 MB
    r = await client.post(
        "/api/imports/sites",
        files={"file": ("big.csv", too_big, "text/csv")},
        cookies={"netforge_session": "sess"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "CSV_TOO_LARGE"


@pytest.mark.asyncio
async def test_import_admin_dry_run_returns_report(client: AsyncClient) -> None:
    # 1st execute: session lookup (handled by _install_db).
    # 2nd execute: csv_import upsert check — return None so the row is treated
    # as a new insert. The driver will then call db.flush() (mocked) and
    # db.rollback() (mocked) because dry_run=True.
    upsert_result = MagicMock()
    upsert_result.scalar_one_or_none = MagicMock(return_value=None)
    _install_db(user=_admin(), execute_returns=[upsert_result])

    r = await client.post(
        "/api/imports/sites",
        files={"file": ("sites.csv", "﻿code;name\nHQ;Headquarters\n".encode(), "text/csv")},
        data={"dry_run": "true"},
        cookies={"netforge_session": "sess"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["parsed_rows"] == 1
    assert body["ok_rows"] == 1
    assert body["applied"] is False  # dry-run always rolls back
    assert body["error_rows"] == []


# --- /api/imports/detect --------------------------------------------------- #


@pytest.mark.asyncio
async def test_detect_rejects_anon(client: AsyncClient) -> None:
    _install_db(user=None)
    r = await client.post(
        "/api/imports/detect",
        files={"file": ("x.csv", b"code;name\n", "text/csv")},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_detect_rejects_viewer(client: AsyncClient) -> None:
    _install_db(user=_viewer())
    r = await client.post(
        "/api/imports/detect",
        files={"file": ("x.csv", b"code;name\n", "text/csv")},
        cookies={"netforge_session": "sess"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_detect_routes_sites_csv(client: AsyncClient) -> None:
    _install_db(user=_admin())
    r = await client.post(
        "/api/imports/detect",
        files={"file": ("sites.csv", b"code;name\nHQ;Headquarters\n", "text/csv")},
        cookies={"netforge_session": "sess"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["entity"] == "sites"
    assert body["confidence"] >= 0.9
    assert body["missing_required"] == []


@pytest.mark.asyncio
async def test_detect_returns_none_when_unknown_headers(client: AsyncClient) -> None:
    _install_db(user=_admin())
    r = await client.post(
        "/api/imports/detect",
        files={"file": ("x.csv", b"foo;bar\n1;2\n", "text/csv")},
        cookies={"netforge_session": "sess"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["entity"] is None
    # The nearest candidate should hint at what columns the user is missing.
    assert body["missing_required"]


@pytest.mark.asyncio
async def test_detect_disambiguates_switches_vs_devices(client: AsyncClient) -> None:
    # Both `_DeviceRow` and `_SwitchRow` require `name`. `port_count` is what
    # tells them apart — without it the row is a device, with it a switch.
    _install_db(user=_admin())
    r = await client.post(
        "/api/imports/detect",
        files={
            "file": (
                "x.csv",
                b"name;type\ncore-01;router\n",
                "text/csv",
            )
        },
        cookies={"netforge_session": "sess"},
    )
    assert r.json()["entity"] == "devices"

    r = await client.post(
        "/api/imports/detect",
        files={
            "file": (
                "x.csv",
                b"name;port_count\ncore-01;48\n",
                "text/csv",
            )
        },
        cookies={"netforge_session": "sess"},
    )
    assert r.json()["entity"] == "switches"


# --- /api/imports/bulk ----------------------------------------------------- #


@pytest.mark.asyncio
async def test_bulk_rejects_anon(client: AsyncClient) -> None:
    _install_db(user=None)
    r = await client.post(
        "/api/imports/bulk",
        files=[("files", ("sites.csv", b"code;name\nX;Y\n", "text/csv"))],
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_bulk_dry_run_routes_two_files(client: AsyncClient) -> None:
    # Each CSV triggers one `select(...).scalar_one_or_none()` per row to look
    # up the existing record; returning None means "new insert".
    new_row = MagicMock()
    new_row.scalar_one_or_none = MagicMock(return_value=None)
    _install_db(user=_admin(), execute_returns=[new_row, new_row])

    site_csv = b"code;name\nHQ;Headquarters\n"
    vlan_csv = b"vlan_id;name\n10;Office\n"

    r = await client.post(
        "/api/imports/bulk",
        files=[
            ("files", ("sites.csv", site_csv, "text/csv")),
            ("files", ("vlans.csv", vlan_csv, "text/csv")),
        ],
        data={"dry_run": "true"},
        cookies={"netforge_session": "sess"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["applied"] is False
    assert body["total_parsed_rows"] == 2
    assert body["total_ok_rows"] == 2

    # Reports are ordered by IMPORT_ORDER — sites (0) comes before vlans (2).
    entities = [f["detected_entity"] for f in body["files"]]
    assert entities == ["sites", "vlans"]


@pytest.mark.asyncio
async def test_bulk_reports_undetectable_file_without_starting_transaction(
    client: AsyncClient,
) -> None:
    _install_db(user=_admin())
    r = await client.post(
        "/api/imports/bulk",
        files=[
            ("files", ("mystery.csv", b"foo;bar\n1;2\n", "text/csv")),
        ],
        cookies={"netforge_session": "sess"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["applied"] is False
    assert body["files"][0]["detected_entity"] is None
    assert body["files"][0]["error_rows"][0]["error"]


@pytest.mark.asyncio
async def test_bulk_zip_explodes_csvs(client: AsyncClient) -> None:
    """A single .zip member is unpacked transparently."""
    import io as _io
    import zipfile as _zf

    new_row = MagicMock()
    new_row.scalar_one_or_none = MagicMock(return_value=None)
    _install_db(user=_admin(), execute_returns=[new_row])

    buf = _io.BytesIO()
    with _zf.ZipFile(buf, "w") as z:
        z.writestr("sites.csv", "code;name\nHQ;Headquarters\n")
    r = await client.post(
        "/api/imports/bulk",
        files=[("files", ("backup.zip", buf.getvalue(), "application/zip"))],
        data={"dry_run": "true"},
        cookies={"netforge_session": "sess"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["files"][0]["filename"] == "sites.csv"
    assert body["files"][0]["detected_entity"] == "sites"


# --- /api/exports ---------------------------------------------------------- #


@pytest.mark.asyncio
async def test_export_unknown_entity_returns_400(client: AsyncClient) -> None:
    _install_db(user=_viewer())
    r = await client.get(
        "/api/exports/frobnicators", cookies={"netforge_session": "sess"}
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "UNKNOWN_ENTITY"


# --- /api/exports/all ------------------------------------------------------ #


@pytest.mark.asyncio
async def test_export_all_rejects_anon(client: AsyncClient) -> None:
    _install_db(user=None)
    r = await client.get("/api/exports/all")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_export_all_rejects_viewer(client: AsyncClient) -> None:
    """`/api/exports/all` is admin-only: it returns the full inventory in
    one in-memory ZIP, so a viewer with an API token could loop the call
    to balloon worker memory or to exfiltrate the entire DB. Match the
    surface to `/api/imports/bulk` (also admin-only)."""
    _install_db(user=_viewer())
    r = await client.get("/api/exports/all", cookies={"netforge_session": "sess"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_export_all_returns_zip_for_admin(client: AsyncClient) -> None:
    """All entities are queried in sequence. Each call to `select(...)` returns
    an empty list — we just want to assert the route assembles a valid ZIP
    with one member per entity, not that the CSV contents are correct (the
    per-entity contents are covered by the streaming export tests).
    """
    import io as _io
    import zipfile as _zf

    # 9 entities → 9 successive db.execute() calls returning empty result sets.
    # The `ports` entity adds one extra inner call (selectinload-style join),
    # but in this mock setup that's still served by the same .scalars()→.all()
    # path, so the same MagicMock works for all of them.
    def _empty_result():
        r = MagicMock()
        r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        r.all = MagicMock(return_value=[])
        return r

    _install_db(
        user=_admin(),
        execute_returns=[_empty_result() for _ in range(9)],
    )

    r = await client.get("/api/exports/all", cookies={"netforge_session": "sess"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert "netforge-export-" in r.headers["content-disposition"]

    zf = _zf.ZipFile(_io.BytesIO(r.content))
    members = {info.filename for info in zf.infolist()}
    # Every entity ships as its own CSV inside the archive — the file names
    # are the ones the bulk importer's auto-detect routes back to the right
    # importer, so this is also the round-trip contract.
    assert members == {
        "sites.csv",
        "rooms.csv",
        "vlans.csv",
        "subnets.csv",
        "ips.csv",
        "devices.csv",
        "switches.csv",
        "ports.csv",
        "links.csv",
    }
    # Each member at minimum contains the BOM + header row.
    for name in members:
        body = zf.read(name).decode("utf-8-sig")
        assert body.split("\n", 1)[0]  # non-empty header line


# --- /api/exports/audit ---------------------------------------------------- #


@pytest.mark.asyncio
async def test_export_audit_rejects_anon(client: AsyncClient) -> None:
    _install_db(user=None)
    r = await client.get("/api/exports/audit")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_export_audit_rejects_viewer(client: AsyncClient) -> None:
    """Same admin gate as GET /api/audit — viewers can't pull the log even
    as CSV."""
    _install_db(user=_viewer())
    r = await client.get("/api/exports/audit", cookies={"netforge_session": "sess"})
    assert r.status_code == 403
    assert r.json()["detail"]["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_export_audit_admin_returns_csv_with_header(client: AsyncClient) -> None:
    """Empty audit log — we still want a CSV file with the expected header
    row (otherwise Excel opens an empty file and the admin thinks the export
    failed silently)."""
    empty = MagicMock()
    empty.all = MagicMock(return_value=[])
    _install_db(user=_admin(), execute_returns=[empty])

    r = await client.get("/api/exports/audit", cookies={"netforge_session": "sess"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "netforge-audit-" in r.headers["content-disposition"]
    body = r.content.decode("utf-8-sig")
    header = body.split("\n", 1)[0]
    # Header must include the joined user_email column — that's the whole
    # reason for the LEFT JOIN against users in the service.
    assert "user_email" in header
    assert "action" in header
    assert "changes" in header
