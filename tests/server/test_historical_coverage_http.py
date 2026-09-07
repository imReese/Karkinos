"""The real coverage GET is bound, provider-free and does not write."""

import socket
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from data.store import DataStore
from server.projections import historical_coverage_persistence as persistence
from server.projections.portfolio_read_snapshot import PortfolioReadSnapshotRejected
from tests.server.test_portfolio_endpoint_read_snapshot import (
    _build_etf_state,
    _fail_independent_read,
    _test_app,
)


def _checkpoint_bytes(tmp_path):
    paths = [tmp_path / name for name in ("app.db", "meta.db")]
    for path in paths:
        with sqlite3.connect(path) as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return {path: path.read_bytes() for path in paths}


def test_real_get_uses_one_ledger_read_and_preserves_financial_inputs(
    monkeypatch, tmp_path
):
    state = _build_etf_state(tmp_path)
    DataStore(tmp_path)
    db = state.require_database()
    before = _checkpoint_bytes(tmp_path)
    count = []
    read = db.get_all_ledger_entries_sync

    def counted():
        count.append(1)
        return read()

    monkeypatch.setattr(db, "get_all_ledger_entries_sync", counted)
    monkeypatch.setattr(
        socket, "create_connection", _fail_independent_read("provider socket")
    )
    for method in (
        "init_sync",
        "publish_current_valuation_snapshot_sync",
        "get_market_bar_on_date_sync",
        "get_latest_quote_before_date_sync",
    ):
        monkeypatch.setattr(db, method, _fail_independent_read(method))
    with TestClient(_test_app(state)) as client:
        response = client.get("/api/portfolio/equity-curve/coverage?range=all")
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["identity"]["ledger_cutoff_id"] == 2
        assert payload["status"] == "unknown"
        assert payload["confirmed_gap_instrument_dates"] == 0
        assert payload["items"]
        assert (
            client.get("/api/portfolio/equity-curve/coverage?range=1m").status_code
            == 422
        )
    assert len(count) == 1
    assert before == {path: path.read_bytes() for path in before}


@pytest.mark.parametrize("target", ["app", "meta"])
def test_get_rejects_drift_outside_base_market_identity(monkeypatch, tmp_path, target):
    state = _build_etf_state(tmp_path)
    DataStore(tmp_path)
    with sqlite3.connect(tmp_path / "meta.db") as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA data_version")
    original = persistence._read_evidence

    def drifting(connection, snapshot):
        evidence = original(connection, snapshot)
        path = tmp_path / ("app.db" if target == "app" else "meta.db")
        with sqlite3.connect(path) as writer:
            writer.execute("CREATE TABLE coverage_drift_fixture (value TEXT)")
        return evidence

    monkeypatch.setattr(persistence, "_read_evidence", drifting)
    with TestClient(_test_app(state)) as client:
        response = client.get("/api/portfolio/equity-curve/coverage")
    assert response.status_code == 503, response.text
    assert "changed" in response.json()["detail"]


def test_missing_source_schema_is_unavailable_and_never_initialized(tmp_path):
    state = _build_etf_state(tmp_path)
    DataStore(tmp_path)
    with sqlite3.connect(tmp_path / "app.db") as connection:
        connection.execute("DROP TABLE instrument_metadata")
    before = _checkpoint_bytes(tmp_path)
    with TestClient(_test_app(state)) as client:
        response = client.get("/api/portfolio/equity-curve/coverage")
    assert response.status_code == 503, response.text
    assert before == {path: path.read_bytes() for path in before}
    with pytest.raises(PortfolioReadSnapshotRejected, match="bound"):
        persistence.read_historical_coverage(SimpleNamespace(db=state.db))


def test_real_get_retains_nav_date_even_when_capture_is_outside_window(tmp_path):
    from datetime import datetime

    from server.config import ServerConfig
    from server.db import AppDatabase
    from server.dependencies import AppState

    DataStore(tmp_path)
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp="2026-09-01T10:00:00+08:00",
        symbol="FIXTURE",
        quantity=10,
        price=2,
        direction="buy",
        asset_class="fund",
    )
    db.save_quote_snapshot_sync(
        symbol="FIXTURE",
        asset_class="fund",
        price=2,
        volume=None,
        timestamp="2026-09-01T15:00:00+08:00",
        nav_date="2026-09-01",
        quote_status="confirmed",
        quote_source="fixture",
        provider_name="fixture",
    )
    db.publish_current_valuation_snapshot_sync(
        now=datetime.fromisoformat("2026-09-01T17:00:00+08:00")
    )
    db.save_quote_snapshot_sync(
        symbol="FIXTURE",
        asset_class="fund",
        price=2,
        volume=None,
        timestamp="2026-09-03T20:00:00+08:00",
        nav_date="2026-09-01 15:00",
        quote_status="confirmed",
        quote_source="fixture",
        provider_name="fixture",
    )
    state = AppState()
    state.db = db
    state.config = ServerConfig()
    with TestClient(_test_app(state)) as client:
        response = client.get("/api/portfolio/equity-curve/coverage")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["end_date"] == "2026-09-01"
    assert payload["items"][0]["valuation_date"] == "2026-09-01"
    assert payload["items"][0]["evidence_status"] == "available"
    assert payload["items"][0]["requirement"] == "unknown"
