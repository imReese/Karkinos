from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from data.market_calendar import build_static_market_calendar_snapshot
from server.db import AppDatabase
from server.routes.market import create_router


class _FixtureCalendarProvider:
    def fetch_snapshot(self, *, exchange: str, year: int):
        return build_static_market_calendar_snapshot(
            exchange=exchange,
            year=year,
            provider="unit_fixture",
            open_dates={"2026-01-02", "2026-01-05"},
            closed_reasons={"2026-01-01": "官方公告：元旦休市"},
            fetched_at="2026-01-06T00:00:00+08:00",
        )


def _client_for_db(monkeypatch, db: AppDatabase) -> TestClient:
    fake_state = SimpleNamespace(
        db=db,
        config=SimpleNamespace(data_source="akshare", tushare_token=""),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app)


def test_market_calendar_sync_persists_snapshot_for_api_consumption(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "market-calendar.db")
    db.init_sync()
    client = _client_for_db(monkeypatch, db)
    monkeypatch.setattr(
        "server.routes.market.build_market_calendar_provider",
        lambda *args, **kwargs: _FixtureCalendarProvider(),
    )

    missing = client.get("/api/market/calendar?exchange=SSE&year=2026")
    assert missing.status_code == 200
    assert missing.json()["status"] == "missing"

    synced = client.post(
        "/api/market/calendar/sync",
        json={"exchange": "SSE", "year": 2026, "provider": "akshare"},
    )

    assert synced.status_code == 200
    payload = synced.json()
    assert payload["exchange"] == "SSE"
    assert payload["year"] == 2026
    assert payload["provider"] == "unit_fixture"
    assert payload["status"] == "available"
    assert payload["trading_day_count"] == 2
    assert payload["closed_day_count"] == 363
    assert payload["official_verification_status"] == "unverified"
    assert payload["days"][0]["schema_version"] == "karkinos.market_calendar.v1"

    fetched = client.get("/api/market/calendar?exchange=SSE&year=2026")
    assert fetched.status_code == 200
    fetched_payload = fetched.json()
    assert fetched_payload["source_fingerprint"] == payload["source_fingerprint"]
    by_date = {day["date"]: day for day in fetched_payload["days"]}
    assert by_date["2026-01-01"]["reason"] == "官方公告：元旦休市"
    assert by_date["2026-01-02"]["is_trading_day"] is True


def test_market_calendar_official_verification_updates_snapshot_metadata(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "market-calendar.db")
    db.init_sync()
    db.upsert_market_calendar_snapshot_sync(
        build_static_market_calendar_snapshot(
            exchange="SSE",
            year=2026,
            provider="unit_fixture",
            open_dates={"2026-01-02"},
            fetched_at="2026-01-06T00:00:00+08:00",
        )
    )
    client = _client_for_db(monkeypatch, db)

    response = client.put(
        "/api/market/calendar/verification",
        json={
            "exchange": "SSE",
            "year": 2026,
            "verification_status": "verified",
            "official_source_url": "https://example.test/exchange-notice",
            "verified_by": "manual-review",
            "review_notes": "Matched official exchange notice.",
            "day_labels": {"2026-01-01": "元旦休市"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["official_verification_status"] == "verified"
    assert payload["official_source_url"] == "https://example.test/exchange-notice"
    assert payload["official_verified_by"] == "manual-review"
    assert "Matched official exchange notice." in payload["limitations"]
    by_date = {day["date"]: day for day in payload["days"]}
    assert by_date["2026-01-01"]["reason"] == "元旦休市"
    assert by_date["2026-01-01"]["reason_code"] == "market_holiday"
