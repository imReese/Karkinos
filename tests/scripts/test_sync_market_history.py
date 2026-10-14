"""Tests for scripts/data/sync_market_history.py CLI entrypoint."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
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


def test_maybe_mirror_to_repo(tmp_path):
    dev_data = tmp_path / "dev"
    dev_data.mkdir()
    dev_meta = dev_data / "meta.db"
    dev_meta.write_text("dev_data_content")

    repo_dir = tmp_path / "repo"
    repo_store = repo_dir / "data" / "store"
    repo_store.mkdir(parents=True)

    with patch("scripts.data.sync_market_history.REPO_ROOT", repo_dir):
        _maybe_mirror_to_repo(dev_data)
        repo_meta = repo_store / "meta.db"
        assert repo_meta.is_file()
        assert repo_meta.read_text() == "dev_data_content"
