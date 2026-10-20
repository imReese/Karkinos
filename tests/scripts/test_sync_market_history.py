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
    _maybe_mirror_to_repo,
    main,
    parse_args,
)
from server.services.market.sync import MarketSyncSummary


def test_parse_args_defaults():
    args = parse_args([])
    assert args.universe == "core"
    assert args.symbols is None
    assert args.start == "2020-01-01"
    assert args.end is None
    assert args.throttle is None
    assert args.exchanges == "SSE,SZSE"
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


@pytest.mark.parametrize(
    "status,expected_code", [("queued", 2), ("failed", 1), ("success", 0)]
)
def test_full_market_cli_uses_shared_service_and_honest_exit_status(
    tmp_path, status, expected_code
):
    service = MagicMock()
    service.sync.return_value = MarketSyncSummary(
        status=status,
        started_at="fixture",
        completed_at="fixture",
        duration_seconds=0,
        error="missing calendar" if status == "failed" else None,
    )
    with patch(
        "scripts.data.sync_market_history.MarketSyncService", return_value=service
    ):
        args = [
            "--universe",
            "full-market",
            "--start",
            "2020-01-01",
            "--end",
            "2026-10-19",
            "--data-dir",
            str(tmp_path),
        ]
        if expected_code:
            with pytest.raises(SystemExit) as exc:
                main(args)
            assert exc.value.code == expected_code
        else:
            main(args)
    req = service.sync.call_args.args[0]
    assert req.universe == "full-market"
    assert req.start_date == "2020-01-01"
    assert req.end_date == "2026-10-19"
    assert req.exchanges == ("SSE", "SZSE")


def test_full_market_rejects_meta_only_mirror_before_submitting(tmp_path):
    with patch("scripts.data.sync_market_history.MarketSyncService") as service:
        with pytest.raises(SystemExit) as exc:
            main(
                [
                    "--universe",
                    "full-market",
                    "--mirror-to-repo",
                    "--data-dir",
                    str(tmp_path),
                ]
            )
        assert exc.value.code == 1
        service.assert_not_called()
