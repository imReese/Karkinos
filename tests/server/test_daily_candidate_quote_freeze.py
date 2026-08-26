from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from server.services.daily_candidate_quote_freeze import (
    DailyCandidateQuoteFreezeService,
)


class _QuoteDb:
    def __init__(self) -> None:
        self.runs: dict[str, dict] = {}
        self.quotes: dict[str, dict] = {}

    def get_quote_fetch_run(self, run_id: str):
        return self.runs.get(run_id)

    def create_quote_fetch_run(self, **payload):
        self.runs[payload["run_id"]] = dict(payload)
        return 1

    def finish_quote_fetch_run(self, *, run_id: str, **payload):
        self.runs[run_id] = {**self.runs[run_id], **payload, "run_id": run_id}
        return self.runs[run_id]

    def get_latest_quote_sync(self, symbol: str, asset_type: str):
        row = self.quotes.get(symbol)
        if row is None or row.get("asset_type") != asset_type:
            return None
        return dict(row)


def _prepared_scan() -> dict:
    return {
        "status": "prepared",
        "decision_date": "2026-08-24",
        "input_fingerprint": "sha256:prepared",
        "signal_selection_fingerprint": "sha256:signals",
        "selected_signals": [
            {"symbol": "600001", "direction": "buy"},
            {"symbol": "000001", "direction": "sell"},
        ],
    }


def test_quote_freeze_refreshes_only_selected_buys_and_reuses_audit() -> None:
    db = _QuoteDb()
    calls: list[str] = []

    async def refresh(_state, symbol, asset_class, *, fetch_run_id):
        calls.append(symbol)
        db.quotes[symbol] = {
            "symbol": symbol,
            "asset_type": asset_class.value,
            "price": 12.34,
            "quote_timestamp": "2026-08-24T09:36:00+08:00",
            "quote_status": "live",
            "provider_name": "fixture",
            "fetch_run_id": fetch_run_id,
        }
        return {
            "symbol": symbol,
            "status": "refreshed",
            "quote_timestamp": "2026-08-24T09:36:00+08:00",
        }

    service = DailyCandidateQuoteFreezeService(
        db=db,
        state=SimpleNamespace(config=SimpleNamespace(data_source="fixture")),
        quote_refresher=refresh,
        clock=lambda: datetime(2026, 8, 24, 9, 36, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    first = asyncio.run(service.run_once(_prepared_scan()))
    second = asyncio.run(service.run_once(_prepared_scan()))

    assert first["status"] == "complete"
    assert first["blockers"] == []
    assert first["symbols"] == ["600001"]
    assert first["provider_contact_performed"] is True
    assert second["status"] == "complete"
    assert second["reused"] is True
    assert calls == ["600001"]
    assert db.runs[first["run_id"]]["trigger"] == (
        "daily_candidate_signal_quote_freeze"
    )


def test_quote_freeze_fails_closed_on_wrong_day_quote() -> None:
    db = _QuoteDb()

    async def refresh(_state, symbol, asset_class, *, fetch_run_id):
        db.quotes[symbol] = {
            "symbol": symbol,
            "asset_type": asset_class.value,
            "price": 12.34,
            "quote_timestamp": "2026-08-21T15:00:00+08:00",
            "quote_status": "live",
            "provider_name": "fixture",
            "fetch_run_id": fetch_run_id,
        }
        return {
            "symbol": symbol,
            "status": "refreshed",
            "quote_timestamp": "2026-08-21T15:00:00+08:00",
        }

    service = DailyCandidateQuoteFreezeService(
        db=db,
        state=SimpleNamespace(config=SimpleNamespace(data_source="fixture")),
        quote_refresher=refresh,
    )

    result = asyncio.run(service.run_once(_prepared_scan()))

    assert result["status"] == "blocked"
    assert "selected_quote_date_mismatch:600001" in result["blockers"]
    assert "selected_quote_fetch_run_not_successful" in result["blockers"]
