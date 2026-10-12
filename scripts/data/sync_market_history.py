#!/usr/bin/env python3
"""Unified market history and facts synchronization CLI entrypoint."""

from __future__ import annotations

import argparse
import logging
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
        choices=["core", "indices", "etfs", "funds", "stocks", "all"],
        help="Universe selection to synchronize. Defaults to 'core' (indices + ETFs + funds + stocks).",
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
        "--force",
        action="store_true",
        help="Force re-fetching and overwriting existing caches.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    data_dir = resolve_data_dir()
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
        "=== Starting Market Synchronization (Universe=%s, Range=%s ~ %s) ===",
        request.universe,
        request.start_date,
        request.end_date or "today",
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
