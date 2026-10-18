"""Tests for scripts/data/sync_market_history.py CLI entrypoint."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from scripts.data.sync_market_history import (
    _load_tushare_token,
    _maybe_mirror_to_repo,
    _sync_full_market_daily,
    main,
    parse_args,
)
from server.services.market_sync import MarketSyncSummary


def test_parse_args_defaults():
    args = parse_args([])
    assert args.universe == "core"
    assert args.symbols is None
    assert args.start == "2020-01-01"
    assert args.end is None
    assert args.throttle == 0.6
    assert args.mirror_to_repo is False
    assert args.force is False


def test_parse_args_full_market_and_custom_options():
    args = parse_args(
        [
            "--universe",
            "full-market",
            "--start",
            "2021-01-01",
            "--end",
            "2024-12-31",
            "--throttle",
            "1.2",
            "--mirror-to-repo",
            "--force",
            "--data-dir",
            "/tmp/karkinos-data",
        ]
    )
    assert args.universe == "full-market"
    assert args.start == "2021-01-01"
    assert args.end == "2024-12-31"
    assert args.throttle == 1.2
    assert args.mirror_to_repo is True
    assert args.force is True
    assert args.data_dir == "/tmp/karkinos-data"


def test_load_tushare_token(monkeypatch, tmp_path):
    monkeypatch.delenv("KARKINOS_TUSHARE_TOKEN", raising=False)
    # 1. From environment
    monkeypatch.setenv("KARKINOS_TUSHARE_TOKEN", "token_from_env_123")
    assert _load_tushare_token() == "token_from_env_123"

    # 2. Unset
    monkeypatch.delenv("KARKINOS_TUSHARE_TOKEN", raising=False)
    with patch("scripts.data.sync_market_history.Path.home", return_value=tmp_path):
        with patch("scripts.data.sync_market_history.REPO_ROOT", tmp_path):
            token = _load_tushare_token()
            assert token is None


def test_main_standard_sync(monkeypatch, tmp_path):
    now = datetime.now()
    mock_summary = MarketSyncSummary(
        status="success",
        total_targets=2,
        successful_targets=2,
        failed_targets=0,
        quotes_updated=2,
        duration_seconds=1.5,
        started_at=now,
        completed_at=now,
    )
    mock_service = MagicMock()
    mock_service.sync.return_value = mock_summary

    with patch(
        "scripts.data.sync_market_history.MarketSyncService", return_value=mock_service
    ):
        main(["--universe", "core", "--data-dir", str(tmp_path)])
        assert mock_service.sync.called
        req = mock_service.sync.call_args[0][0]
        assert req.universe == "core"


def test_sync_full_market_daily_missing_token(monkeypatch, tmp_path):
    monkeypatch.delenv("KARKINOS_TUSHARE_TOKEN", raising=False)
    with patch(
        "scripts.data.sync_market_history._load_tushare_token", return_value=None
    ):
        rc = _sync_full_market_daily(
            data_dir=tmp_path,
            start_date="2021-01-01",
            end_date="2021-01-05",
            throttle=0.0,
        )
        assert rc == 1


def test_sync_full_market_daily_success(monkeypatch, tmp_path):
    with (
        patch(
            "scripts.data.sync_market_history._load_tushare_token",
            return_value="dummy_token",
        ),
        patch(
            "data.store.DataStore.get_market_daily_ingestion_receipt", return_value=None
        ),
        patch("data.store.DataStore.ingest_market_daily_batch") as mock_ingest,
        patch(
            "data.providers.tushare.TushareSource.fetch_market_daily_bars"
        ) as mock_fetch,
    ):
        mock_fetch.return_value = pd.DataFrame(
            [
                {
                    "symbol": "600000",
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.8,
                    "close": 10.2,
                    "volume": 1000,
                }
            ]
        )

        with patch(
            "server.persistence.market_calendar.MarketCalendarRepository"
        ) as mock_cal_repo:
            repo_instance = MagicMock()
            repo_instance.get_snapshot.return_value = {
                "days_json": '[{"date": "2021-01-04", "is_trading_day": true}]'
            }
            mock_cal_repo.return_value = repo_instance
            app_db = tmp_path / "app.db"
            app_db.touch()

            rc = _sync_full_market_daily(
                data_dir=tmp_path,
                start_date="2021-01-01",
                end_date="2021-01-05",
                throttle=0.0,
            )
            assert rc == 0
            assert mock_fetch.called
            assert mock_ingest.called


@pytest.mark.parametrize("destination_locked", [False, True])
def test_maybe_mirror_to_repo_keeps_committed_wal_and_active_snapshots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, destination_locked: bool
) -> None:
    from data.store import DataStore
    from scripts.data import sync_market_history

    dev_data = tmp_path / "dev"
    repo_dir = tmp_path / "repo"
    repo_store = repo_dir / "data" / "store"
    source = DataStore(dev_data)
    target = DataStore(repo_store)
    monkeypatch.setattr(sync_market_history, "REPO_ROOT", repo_dir)
    first = pd.DataFrame(
        [
            {
                "symbol": "600000",
                "timestamp": pd.Timestamp("2026-10-12"),
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "volume": 1000.0,
                "amount": 10500.0,
            }
        ]
    )
    for store in (source, target):
        store.ingest_market_daily_batch(
            trade_date="2026-10-12", provider_name="tushare", bars=first
        )
    first_receipt = target.get_market_daily_ingestion_receipt(
        trade_date="2026-10-12", provider_name="tushare"
    )
    assert first_receipt is not None

    with (
        closing(sqlite3.connect(dev_data / "meta.db")) as source_reader,
        closing(sqlite3.connect(repo_store / "meta.db")) as target_reader,
    ):
        for reader in (source_reader, target_reader):
            assert reader.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            reader.execute("BEGIN")
            assert reader.execute("SELECT count(*) FROM market_bars").fetchone() == (1,)
        second = first.copy()
        second["timestamp"] = pd.Timestamp("2026-10-13")
        source.ingest_market_daily_batch(
            trade_date="2026-10-13", provider_name="tushare", bars=second
        )
        assert (
            source.get_market_daily_ingestion_receipt(
                trade_date="2026-10-13", provider_name="tushare"
            )
            is not None
        )
        assert (dev_data / "meta.db-wal").is_file()
        assert (repo_store / "meta.db-wal").is_file()

        if destination_locked:
            # Keep a real WAL writer active; the backup must stop at its deadline
            # and leave the previously committed target readable and unchanged.
            with closing(sqlite3.connect(repo_store / "meta.db")) as writer:
                writer.execute("BEGIN IMMEDIATE")
                monotonic = MagicMock(side_effect=[0.0, 31.0])
                monkeypatch.setattr("time.monotonic", monotonic)
                with pytest.raises(TimeoutError, match="market_meta_mirror_timeout"):
                    _maybe_mirror_to_repo(dev_data)
                writer.rollback()
        else:
            _maybe_mirror_to_repo(dev_data)

        for reader in (source_reader, target_reader):
            assert reader.execute("SELECT count(*) FROM market_bars").fetchone() == (1,)
        with closing(sqlite3.connect(repo_store / "meta.db")) as current:
            assert current.execute("PRAGMA quick_check").fetchall() == [("ok",)]
            expected_count = 1 if destination_locked else 2
            assert current.execute("SELECT count(*) FROM market_bars").fetchone() == (
                expected_count,
            )
            assert current.execute(
                "SELECT count(*) FROM market_daily_ingestion_receipts"
            ).fetchone() == (expected_count,)

    assert (
        target.get_market_daily_ingestion_receipt(
            trade_date="2026-10-12", provider_name="tushare"
        )
        == first_receipt
    )
    assert (
        target.get_market_daily_ingestion_receipt(
            trade_date="2026-10-13", provider_name="tushare"
        )
        is not None
    ) is (not destination_locked)


def test_full_market_interrupt_exits_nonzero_and_resumes_missing_dates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.types import BarFrequency, InstrumentType
    from data.store import DataStore
    from scripts.data import sync_market_history

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "app.db").touch()
    monkeypatch.setenv("KARKINOS_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sync_market_history, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sync_market_history.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        sync_market_history, "_load_tushare_token", lambda: "synthetic-unused-token"
    )
    calendar = MagicMock()
    calendar.get_snapshot.return_value = {
        "days_json": (
            '[{"date":"2026-10-12","is_trading_day":true},'
            '{"date":"2026-10-13","is_trading_day":true}]'
        )
    }
    monkeypatch.setattr(
        "server.persistence.market_calendar.MarketCalendarRepository",
        lambda _path: calendar,
    )
    requested_dates: list[str] = []
    interrupted = False

    def fetch(_source: object, trade_date: str) -> pd.DataFrame:
        nonlocal interrupted
        requested_dates.append(trade_date)
        if trade_date == "2026-10-13" and not interrupted:
            interrupted = True
            raise KeyboardInterrupt
        return pd.DataFrame(
            [
                {
                    "symbol": "600000",
                    "timestamp": pd.Timestamp(trade_date),
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.0,
                    "close": 10.5,
                    "volume": 1000.0,
                    "amount": 10500.0,
                }
            ]
        )

    monkeypatch.setattr(
        "data.providers.tushare.TushareSource.fetch_market_daily_bars", fetch
    )
    arguments = [
        "--universe",
        "full-market",
        "--start",
        "2026-10-12",
        "--end",
        "2026-10-13",
        "--throttle",
        "0",
        "--data-dir",
        str(data_dir),
    ]
    with pytest.raises(SystemExit) as result:
        main(arguments)
    assert result.value.code == 130
    assert requested_dates == ["2026-10-12", "2026-10-13"]

    store = DataStore(data_dir)
    first_receipt = store.get_market_daily_ingestion_receipt(
        trade_date="2026-10-12", provider_name="tushare"
    )
    assert first_receipt is not None
    assert first_receipt["row_count"] == 1
    assert (
        store.get_market_daily_ingestion_receipt(
            trade_date="2026-10-13", provider_name="tushare"
        )
        is None
    )
    first_bars = store.load_bars(
        "600000", BarFrequency.DAILY, instrument_type=InstrumentType.STOCK
    )
    assert first_bars is not None
    assert first_bars["timestamp"].dt.strftime("%Y-%m-%d").tolist() == ["2026-10-12"]

    requested_dates.clear()
    main(arguments)
    assert requested_dates == ["2026-10-13"]
    assert (
        store.get_market_daily_ingestion_receipt(
            trade_date="2026-10-12", provider_name="tushare"
        )
        == first_receipt
    )
    second_receipt = store.get_market_daily_ingestion_receipt(
        trade_date="2026-10-13", provider_name="tushare"
    )
    assert second_receipt is not None
    assert second_receipt["row_count"] == 1
    bars = store.load_bars(
        "600000", BarFrequency.DAILY, instrument_type=InstrumentType.STOCK
    )
    assert bars is not None
    assert bars["timestamp"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-10-12",
        "2026-10-13",
    ]

    requested_dates.clear()
    main(arguments)
    assert requested_dates == []
    assert (
        store.get_market_daily_ingestion_receipt(
            trade_date="2026-10-13", provider_name="tushare"
        )
        == second_receipt
    )


@pytest.mark.parametrize("local_database_exists", [False, True])
def test_full_market_calendar_fallback_uses_canonical_snapshot_and_saves_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, local_database_exists: bool
) -> None:
    from core.types import BarFrequency, InstrumentType
    from data.market_calendar import build_static_market_calendar_snapshot
    from data.store import DataStore
    from scripts.data import sync_market_history

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    if local_database_exists:
        (data_dir / "app.db").touch()
    monkeypatch.setenv("KARKINOS_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sync_market_history, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sync_market_history.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        sync_market_history, "_load_tushare_token", lambda: "synthetic-unused-token"
    )
    repository = MagicMock()
    repository.get_snapshot.return_value = None
    repository_factory = MagicMock(return_value=repository)
    monkeypatch.setattr(
        "server.persistence.market_calendar.MarketCalendarRepository",
        repository_factory,
    )
    snapshot = build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2026,
        provider="synthetic",
        open_dates=["2026-10-09", "2026-10-12", "2026-10-13", "2026-10-15"],
        fetched_at="2026-10-16T00:00:00+08:00",
    )
    fetch_snapshot = MagicMock(return_value=snapshot)
    calendar_factory = MagicMock(
        return_value=SimpleNamespace(fetch_snapshot=fetch_snapshot)
    )
    monkeypatch.setattr(
        "data.market_calendar.build_market_calendar_provider", calendar_factory
    )
    fetched_dates: list[str] = []

    def fetch(_source: object, trade_date: str) -> pd.DataFrame:
        fetched_dates.append(trade_date)
        return pd.DataFrame(
            [
                {
                    "symbol": "600000",
                    "timestamp": pd.Timestamp(trade_date),
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.0,
                    "close": 10.5,
                    "volume": 1000.0,
                    "amount": 10500.0,
                }
            ]
        )

    monkeypatch.setattr(
        "data.providers.tushare.TushareSource.fetch_market_daily_bars", fetch
    )
    main(
        [
            "--universe",
            "full-market",
            "--start",
            "2026-10-10",
            "--end",
            "2026-10-14",
            "--throttle",
            "0",
            "--data-dir",
            str(data_dir),
        ]
    )

    assert repository_factory.call_count == int(local_database_exists)
    if local_database_exists:
        repository.get_snapshot.assert_called_once_with(exchange="SSE", year=2026)
    calendar_factory.assert_called_once_with("akshare")
    fetch_snapshot.assert_called_once_with(exchange="SSE", year=2026)
    assert fetched_dates == ["2026-10-12", "2026-10-13"]
    store = DataStore(data_dir)
    for day in fetched_dates:
        receipt = store.get_market_daily_ingestion_receipt(
            trade_date=day, provider_name="tushare"
        )
        assert receipt is not None
        assert receipt["row_count"] == 1
    bars = store.load_bars(
        "600000", BarFrequency.DAILY, instrument_type=InstrumentType.STOCK
    )
    assert bars is not None
    assert bars["timestamp"].dt.strftime("%Y-%m-%d").tolist() == fetched_dates


@pytest.mark.parametrize("local_years", [(2025,), (2026,), (), (2025, 2026)])
def test_full_market_fills_each_missing_calendar_year_and_reuses_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, local_years: tuple[int, ...]
) -> None:
    from core.types import BarFrequency, InstrumentType
    from data.market_calendar import build_static_market_calendar_snapshot
    from data.store import DataStore
    from scripts.data import sync_market_history
    from server.db import AppDatabase
    from server.persistence.market_calendar import MarketCalendarRepository

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    AppDatabase(data_dir / "app.db").init_sync()
    repo = MarketCalendarRepository(str(data_dir / "app.db"))
    snapshots = {
        year: build_static_market_calendar_snapshot(
            exchange="SSE",
            year=year,
            provider="synthetic",
            open_dates=[day],
            fetched_at="2026-01-06T00:00:00+08:00",
        )
        for year, day in [(2025, "2025-12-31"), (2026, "2026-01-05")]
    }
    for year in local_years:
        repo.upsert_snapshot(snapshots[year])
    monkeypatch.setattr(sync_market_history, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sync_market_history.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sync_market_history, "_load_tushare_token", lambda: "fixture")
    calendar_requests = []

    def fetch_calendar(*, exchange, year):
        assert exchange == "SSE"
        calendar_requests.append(year)
        return snapshots[year]

    monkeypatch.setattr(
        "data.market_calendar.build_market_calendar_provider",
        lambda _name: SimpleNamespace(fetch_snapshot=fetch_calendar),
    )
    bar_requests = []

    def fetch_bars(_source, trade_date):
        bar_requests.append(trade_date)
        return pd.DataFrame(
            [
                {
                    "symbol": "600000",
                    "timestamp": pd.Timestamp(trade_date),
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.0,
                    "close": 10.5,
                    "volume": 1000.0,
                    "amount": 10500.0,
                }
            ]
        )

    monkeypatch.setattr(
        "data.providers.tushare.TushareSource.fetch_market_daily_bars", fetch_bars
    )
    arguments = [
        "--universe",
        "full-market",
        "--start",
        "2025-12-31",
        "--end",
        "2026-01-05",
        "--throttle",
        "0",
        "--data-dir",
        str(data_dir),
    ]
    main(arguments)
    assert calendar_requests == [
        year for year in (2025, 2026) if year not in local_years
    ]
    assert bar_requests == ["2025-12-31", "2026-01-05"]
    store = DataStore(data_dir)
    receipts = {
        day: store.get_market_daily_ingestion_receipt(
            trade_date=day, provider_name="tushare"
        )
        for day in bar_requests
    }
    assert all(
        receipt is not None and receipt["row_count"] == 1
        for receipt in receipts.values()
    )
    bars = store.load_bars(
        "600000", BarFrequency.DAILY, instrument_type=InstrumentType.STOCK
    )
    assert bars is not None
    assert bars["timestamp"].dt.strftime("%Y-%m-%d").tolist() == bar_requests
    bar_requests.clear()
    main(arguments)
    assert bar_requests == []
    assert {
        day: store.get_market_daily_ingestion_receipt(
            trade_date=day, provider_name="tushare"
        )
        for day in receipts
    } == receipts


@pytest.mark.parametrize(
    "calendar_state", ["closed", "empty-cache", "provider-fails", "provider-empty"]
)
def test_full_market_calendar_distinguishes_closed_days_from_missing_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, calendar_state: str
) -> None:
    from dataclasses import replace

    from data.market_calendar import build_static_market_calendar_snapshot
    from scripts.data import sync_market_history
    from server.db import AppDatabase
    from server.persistence.market_calendar import MarketCalendarRepository

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    AppDatabase(data_dir / "app.db").init_sync()
    repo = MarketCalendarRepository(str(data_dir / "app.db"))
    snapshot = build_static_market_calendar_snapshot(
        exchange="SSE",
        year=2026,
        provider="synthetic",
        open_dates=["2026-01-05"],
        fetched_at="2026-01-06T00:00:00+08:00",
    )
    if calendar_state in {"closed", "empty-cache"}:
        repo.upsert_snapshot(
            snapshot if calendar_state == "closed" else replace(snapshot, days=())
        )
    monkeypatch.setattr(sync_market_history, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sync_market_history.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sync_market_history, "_load_tushare_token", lambda: "fixture")
    fetch_calendar = MagicMock(
        return_value=replace(snapshot, days=())
        if calendar_state == "provider-empty"
        else snapshot
    )
    if calendar_state == "provider-fails":
        fetch_calendar.side_effect = OSError("synthetic calendar unavailable")
    monkeypatch.setattr(
        "data.market_calendar.build_market_calendar_provider",
        lambda _name: SimpleNamespace(fetch_snapshot=fetch_calendar),
    )
    fetch_bars = MagicMock(
        side_effect=AssertionError("No bars without an open session")
    )
    monkeypatch.setattr(
        "data.providers.tushare.TushareSource.fetch_market_daily_bars", fetch_bars
    )
    arguments = [
        "--universe",
        "full-market",
        "--start",
        "2026-01-03",
        "--end",
        "2026-01-04",
        "--throttle",
        "0",
        "--data-dir",
        str(data_dir),
    ]
    if calendar_state in {"provider-fails", "provider-empty"}:
        with pytest.raises(SystemExit) as result:
            main(arguments)
        assert result.value.code == 1
    else:
        main(arguments)
    assert fetch_calendar.call_count == int(calendar_state != "closed")
    fetch_bars.assert_not_called()
