from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from server.db import AppDatabase
from server.persistence.event_log import EventLogRepository
from server.routes.market import create_router

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


def _app(monkeypatch, database: AppDatabase | None) -> FastAPI:
    monkeypatch.setattr(
        "server.dependencies.get_app_state",
        lambda: SimpleNamespace(db=database),
    )
    app = FastAPI()
    app.include_router(create_router())
    return app


async def test_concurrent_note_creates_return_each_committed_record(
    tmp_path, monkeypatch
) -> None:
    database = AppDatabase(tmp_path / "notes.db")
    database.init_sync()
    app = _app(monkeypatch, database)
    add = database.add_research_note
    committed: list[int] = []
    both_committed = asyncio.Event()

    async def add_before_response(**payload):
        note_id = await add(**payload)
        committed.append(note_id)
        if len(committed) == 2:
            both_committed.set()
        # Force the response lookup to run after both real SQLite commits.
        await asyncio.wait_for(both_committed.wait(), timeout=5)
        return note_id

    monkeypatch.setattr(database, "add_research_note", add_before_response)
    payloads = [
        {
            "symbol": symbol,
            "title": f"Research {symbol}",
            "content": f"Persisted evidence {symbol}",
        }
        for symbol in ("600519", "510300")
    ]
    async with (
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as first,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as second,
    ):
        responses = await asyncio.gather(
            first.post("/api/market/research-notes", json=payloads[0]),
            second.post("/api/market/research-notes", json=payloads[1]),
        )

    assert [response.status_code for response in responses] == [200, 200]
    for response, expected in zip(responses, payloads, strict=True):
        actual = response.json()
        assert {key: actual[key] for key in expected} == expected
        assert actual["id"] in committed
    assert len({response.json()["id"] for response in responses}) == 2
    stored = await database.get_research_notes(limit=10)
    assert {row["id"] for row in stored} == set(committed)
    events = EventLogRepository(database.path).list_events(
        event_type="research.note.created"
    )
    assert len(events) == 2
    assert {event["source_ref"] for event in events} == {
        str(note_id) for note_id in committed
    }


async def test_note_update_reads_its_id_outside_global_latest_window(
    tmp_path, monkeypatch
) -> None:
    database = AppDatabase(tmp_path / "notes.db")
    database.init_sync()
    note_id = await database.add_research_note(
        symbol="600519",
        asset_class="stock",
        entry_kind="note",
        title="Original",
        content="Original evidence",
    )
    # Other notes may sort ahead, for example after a local clock correction.
    # Updating an exact ID must not depend on a bounded global list response.
    with sqlite3.connect(database.path) as connection:
        connection.executemany(
            """INSERT INTO market_research_notes
               (symbol, asset_class, entry_kind, title, content, priority,
                created_at, updated_at)
               VALUES (?, 'stock', 'note', ?, 'Other evidence', 'normal', ?, ?)""",
            [
                ("000001", f"Other {index}", "2099-01-01", "2099-01-01")
                for index in range(201)
            ],
        )
    assert note_id not in {
        row["id"] for row in await database.get_research_notes(limit=200)
    }
    app = _app(monkeypatch, database)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.put(
            f"/api/market/research-notes/{note_id}",
            json={"title": "Updated", "content": "Reviewed evidence"},
        )

    assert response.status_code == 200
    assert response.json()["id"] == note_id
    assert response.json()["symbol"] == "600519"
    assert response.json()["title"] == "Updated"
    assert response.json()["content"] == "Reviewed evidence"


async def test_note_missing_id_and_unavailable_storage_keep_http_statuses(
    tmp_path, monkeypatch
) -> None:
    database = AppDatabase(tmp_path / "notes.db")
    database.init_sync()
    app = _app(monkeypatch, database)
    payload = {"title": "Research", "content": "Evidence"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        missing = await client.put("/api/market/research-notes/999", json=payload)
        assert missing.status_code == 404
        monkeypatch.setattr(
            "server.dependencies.get_app_state", lambda: SimpleNamespace(db=None)
        )
        for method, url, body in (
            ("POST", "/api/market/research-notes", {"symbol": "600519", **payload}),
            ("PUT", "/api/market/research-notes/999", payload),
        ):
            response = await client.request(method, url, json=body)
            assert response.status_code == 503
