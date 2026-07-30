"""`build_zip` RAM cap (Fix #12).

`build_zip` assembles the whole `/api/exports/all` ZIP in memory (see its
docstring for why that's an accepted trade-off for v1). Without a cap, an
unexpectedly huge inventory (or a bug that makes `stream_export` loop
forever) grows that in-memory buffer without bound. These tests fake
`stream_export` so we don't need a real DB / all nine entity queries —
only `build_zip`'s own bookkeeping is under test.
"""

from __future__ import annotations

import zipfile
from collections.abc import AsyncIterator
from io import BytesIO
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.services import csv_export as service


@pytest.mark.asyncio
async def test_build_zip_refuses_once_the_cap_is_exceeded(monkeypatch) -> None:
    async def fake_stream_export(db, entity) -> AsyncIterator[str]:
        yield "x" * 1000

    monkeypatch.setattr(service, "stream_export", fake_stream_export)
    monkeypatch.setattr(service, "EXPORT_ZIP_MAX_UNCOMPRESSED_BYTES", 500)

    with pytest.raises(HTTPException) as exc:
        await service.build_zip(AsyncMock())
    assert exc.value.status_code == 400
    assert exc.value.detail["error"]["code"] == "EXPORT_TOO_LARGE"


@pytest.mark.asyncio
async def test_build_zip_succeeds_when_under_the_cap(monkeypatch) -> None:
    async def fake_stream_export(db, entity) -> AsyncIterator[str]:
        yield f"{entity}-row\n"

    monkeypatch.setattr(service, "stream_export", fake_stream_export)
    monkeypatch.setattr(service, "EXPORT_ZIP_MAX_UNCOMPRESSED_BYTES", 10_000)

    payload = await service.build_zip(AsyncMock())
    assert isinstance(payload, bytes)
    with zipfile.ZipFile(BytesIO(payload)) as zf:
        assert set(zf.namelist()) == {f"{e}.csv" for e in service.ENTITIES}
