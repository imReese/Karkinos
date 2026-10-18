#!/usr/bin/env python3
"""Unified market history and facts synchronization CLI entrypoint."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.runtime_paths import resolve_data_dir
from server.services.market_sync import (
    MarketSyncRequest,
    MarketSyncService,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sync_market_history")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync and backfill market history and real-time facts into Karkinos local data plane."
    )
    parser.add_argument(
        "--universe",
        default="core",
        choices=["core", "indices", "etfs", "funds", "stocks", "all", "full-market"],
        help="Universe selection to synchronize. Defaults to 'core' (indices + ETFs + funds + stocks). Use 'full-market' for full A-share daily batch backfill.",
    )
    parser.add_argument(
        "--symbols",
        default=None,
        help="Optional comma-separated list of symbols (e.g. '600519,300750') to sync directly.",
    )
    parser.add_argument(
        "--asset-class",
        default=None,
        choices=["stock", "fund", "index"],
        help="Asset class when passing arbitrary --symbols. Auto-detected if omitted.",
    )
    parser.add_argument(
        "--start",
        default="2020-01-01",
        help="Start date YYYY-MM-DD. Defaults to '2020-01-01'.",
    )
    parser.add_argument(
        "--end",
        default=None,
        help="End date YYYY-MM-DD. Defaults to current date.",
    )
    parser.add_argument(
        "--throttle",
        type=float,
        default=0.6,
        help="Throttle delay in seconds between remote provider requests (used by full-market sync, default: 0.6s).",
    )
    parser.add_argument(
        "--skip-calendar",
        action="store_true",
        help="Skip trading calendar synchronization.",
    )
    parser.add_argument(
        "--skip-quotes",
        action="store_true",
        help="Skip latest quote snapshot update.",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Target data directory. Defaults to development data directory if present, or canonical resolve_data_dir().",
    )
    parser.add_argument(
        "--mirror-to-repo",
        action="store_true",
        help="Mirror the resulting meta.db back to ./data/store/meta.db after completion.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-fetching and overwriting existing caches.",
    )
    return parser.parse_args(argv)


def _load_tushare_token() -> str | None:
    token = os.environ.get("KARKINOS_TUSHARE_TOKEN")
    if token:
        return token
    dev_env = Path.home() / ".karkinos/development/config/.env"
    if dev_env.is_file():
        for line in dev_env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("KARKINOS_TUSHARE_TOKEN="):
                val = line.split("=", 1)[1].strip().strip("'\"")
                if val:
                    os.environ["KARKINOS_TUSHARE_TOKEN"] = val
                    return val
    repo_env = REPO_ROOT / ".env"
    if repo_env.is_file():
        for line in repo_env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("KARKINOS_TUSHARE_TOKEN="):
                val = line.split("=", 1)[1].strip().strip("'\"")
                if val:
                    os.environ["KARKINOS_TUSHARE_TOKEN"] = val
                    return val
    return None


def _sync_full_market_daily(
    data_dir: Path,
    start_date: str,
    end_date: str,
    throttle: float,
    force: bool = False,
) -> int:
    import json
    import time

    from data.providers.tushare import TushareSource
    from data.store import DataStore
    from server.persistence.market_calendar import MarketCalendarRepository

    token = _load_tushare_token()
    if not token:
        logger.error(
            "KARKINOS_TUSHARE_TOKEN is required in environment or .env for full-market sync"
        )
        return 1

    store = DataStore(data_dir)
    source = TushareSource()

    # Query trading calendar from local app.db (SSE exchange)
    app_db = data_dir / "app.db"
    if not app_db.is_file():
        app_db = REPO_ROOT / "data/store/app.db"

    start_year = int(start_date[:4])
    end_year = int(end_date[:4])
    all_trade_dates: list[str] = []

    repo = MarketCalendarRepository(str(app_db)) if app_db.is_file() else None
    provider = None
    try:
        for y in range(start_year, end_year + 1):
            cached = repo.get_snapshot(exchange="SSE", year=y) if repo else None
            days = (
                json.loads(cached["days_json"])
                if cached and cached.get("days_json")
                else []
            )
            if not days:
                from data.market_calendar import build_market_calendar_provider

                if provider is None:
                    provider = build_market_calendar_provider("akshare")
                snap = provider.fetch_snapshot(exchange="SSE", year=y)
                if (
                    snap.year != y
                    or snap.exchange != "SSE"
                    or snap.status != "available"
                    or not snap.days
                ):
                    raise ValueError(f"market calendar unavailable for SSE/{y}")
                days = [day.to_payload() for day in snap.days]
            for d in days:
                dt = d.get("date")
                if dt and d.get("is_trading_day") and start_date <= dt <= end_date:
                    all_trade_dates.append(dt)
    except KeyboardInterrupt:
        return 130
    except Exception:
        logger.exception(
            "Unable to resolve complete trading calendar for %s ~ %s",
            start_date,
            end_date,
        )
        return 1

    all_trade_dates.sort()
    logger.info(
        "Total trading days in requested range (%s ~ %s): %d",
        start_date,
        end_date,
        len(all_trade_dates),
    )

    missing_dates: list[str] = []
    for td in all_trade_dates:
        if force:
            missing_dates.append(td)
        else:
            receipt = store.get_market_daily_ingestion_receipt(
                trade_date=td, provider_name="tushare", verify=False
            )
            if receipt is None:
                missing_dates.append(td)

    logger.info(
        "Already ingested: %d, Missing to backfill: %d",
        len(all_trade_dates) - len(missing_dates),
        len(missing_dates),
    )

    if not missing_dates:
        logger.info(
            "All trading dates in range %s ~ %s are already ingested!",
            start_date,
            end_date,
        )
        return 0

    success_count = 0
    fail_count = 0
    total_missing = len(missing_dates)

    logger.info("Starting bulk daily backfill for %d trading dates...", total_missing)
    start_time = time.time()

    for idx, trade_date in enumerate(missing_dates, start=1):
        try:
            bars_df = source.fetch_market_daily_bars(trade_date)
            if bars_df is None or bars_df.empty:
                logger.warning(
                    "[%d/%d] %s: No bars returned", idx, total_missing, trade_date
                )
                fail_count += 1
                continue

            store.ingest_market_daily_batch(
                trade_date=trade_date,
                provider_name="tushare",
                bars=bars_df,
            )
            success_count += 1
            if idx % 10 == 0 or idx == total_missing:
                elapsed = time.time() - start_time
                rate = success_count / elapsed if elapsed > 0 else 0
                remaining = (total_missing - idx) / rate if rate > 0 else 0
                logger.info(
                    "[%d/%d] Ingested %s (%d stocks) | Rate: %.1f days/s | Est. remaining: %.1f min",
                    idx,
                    total_missing,
                    trade_date,
                    len(bars_df),
                    rate,
                    remaining / 60,
                )
            time.sleep(throttle)
        except KeyboardInterrupt:
            logger.warning(
                "Interrupted by user. Progress saved up to last completed date."
            )
            return 130
        except Exception as exc:
            logger.error(
                "[%d/%d] Failed to ingest %s: %s",
                idx,
                total_missing,
                trade_date,
                exc,
                exc_info=True,
            )
            fail_count += 1
            time.sleep(max(throttle, 2.0))

    elapsed = time.time() - start_time
    logger.info(
        "=== Full-market daily backfill finished in %.1f minutes: Success=%d, Failed=%d ===",
        elapsed / 60,
        success_count,
        fail_count,
    )
    return 0 if fail_count == 0 else 1


def _maybe_mirror_to_repo(data_dir: Path) -> None:
    repo_meta = REPO_ROOT / "data/store/meta.db"
    dev_meta = data_dir / "meta.db"
    if (
        dev_meta.is_file()
        and repo_meta.parent.is_dir()
        and dev_meta.resolve() != repo_meta.resolve()
    ):
        logger.info("Mirroring %s -> %s...", dev_meta, repo_meta)
        import time
        from contextlib import closing

        from data.meta_store_connection import connect_meta_sqlite

        deadline = time.monotonic() + 30

        def progress(_status: int, _remaining: int, _total: int) -> None:
            if time.monotonic() >= deadline:
                raise TimeoutError("market_meta_mirror_timeout")

        with closing(connect_meta_sqlite(dev_meta, readonly=True)) as source:
            with closing(connect_meta_sqlite(repo_meta)) as target:
                # SQLite commits the snapshot to the existing target atomically,
                # retaining valid WAL sidecars and snapshots of active readers.
                source.backup(target, pages=256, progress=progress, sleep=0.05)
        logger.info("Mirror complete.")


def main(argv: list[str] | None = None) -> None:
    from datetime import datetime

    args = parse_args(argv)
    dev_data = Path.home() / ".karkinos/development/data"
    fallback_dir = str(dev_data) if dev_data.is_dir() else resolve_data_dir()
    data_dir = Path(
        args.data_dir or os.environ.get("KARKINOS_DATA_DIR") or fallback_dir
    )

    end_date = args.end or datetime.now().strftime("%Y-%m-%d")

    if args.universe == "full-market":
        logger.info(
            "=== Starting Full-Market Daily Backfill (Range=%s ~ %s, DataDir=%s) ===",
            args.start,
            end_date,
            data_dir,
        )
        rc = _sync_full_market_daily(
            data_dir=data_dir,
            start_date=args.start,
            end_date=end_date,
            throttle=args.throttle,
            force=args.force,
        )
        if args.mirror_to_repo:
            _maybe_mirror_to_repo(data_dir)
        if rc != 0:
            sys.exit(rc)
        return

    service = MarketSyncService(data_dir=data_dir)

    raw_symbols = (
        [s.strip() for s in args.symbols.split(",") if s.strip()]
        if args.symbols
        else None
    )

    request = MarketSyncRequest(
        universe=args.universe,
        symbols=raw_symbols,
        asset_class=args.asset_class,
        start_date=args.start,
        end_date=args.end,
        skip_calendar=args.skip_calendar,
        skip_quotes=args.skip_quotes,
        force=args.force,
    )

    logger.info(
        "=== Starting Market Synchronization (Universe=%s, Range=%s ~ %s, DataDir=%s) ===",
        request.universe,
        request.start_date,
        request.end_date or "today",
        data_dir,
    )

    summary = service.sync(request)

    logger.info(
        "=== Market Sync Completed in %.2fs: Status=%s, Total=%d, Success=%d, Failed=%d, QuotesUpdated=%d ===",
        summary.duration_seconds,
        summary.status,
        summary.total_targets,
        summary.successful_targets,
        summary.failed_targets,
        summary.quotes_updated,
    )

    if args.mirror_to_repo:
        _maybe_mirror_to_repo(data_dir)

    if summary.failed_targets > 0:
        for item in summary.items:
            if item.status == "failed":
                logger.error(
                    "Failed target: %s (%s) - %s",
                    item.symbol,
                    item.instrument_type,
                    item.error,
                )
        sys.exit(1)


if __name__ == "__main__":
    main()
