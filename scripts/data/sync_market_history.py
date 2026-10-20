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
from server.services.market.sync import (
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
        help="Universe selection to synchronize. Defaults to 'core' (indices + ETFs + funds + stocks). Use 'full-market' for durable verified history jobs (default scope: SSE + SZSE).",
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
        help="End date YYYY-MM-DD. Defaults to today; full-market stops before today's collection cutoff if needed.",
    )
    parser.add_argument(
        "--throttle",
        type=float,
        default=None,
        help="Deprecated compatibility option; background worker controls provider pacing.",
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
        help="Re-fetch ordinary caches; for full-market, request a new observation round without overwriting evidence.",
    )
    parser.add_argument(
        "--exchanges",
        default="SSE,SZSE",
        help="Full-market exchange scope: SSE,SZSE (default); add BSE explicitly if needed.",
    )
    parser.add_argument(
        "--universe-snapshot-id",
        default=None,
        help="Reuse an exact persisted stock-master observation for repeatable full-market scope.",
    )
    return parser.parse_args(argv)


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
    args = parse_args(argv)
    dev_data = Path.home() / ".karkinos/development/data"
    fallback_dir = str(dev_data) if dev_data.is_dir() else resolve_data_dir()
    data_dir = Path(
        args.data_dir or os.environ.get("KARKINOS_DATA_DIR") or fallback_dir
    )

    if args.universe == "full-market" and args.mirror_to_repo:
        logger.error(
            "Full-market history is stored in app.db and research/; meta.db mirroring is insufficient"
        )
        sys.exit(1)
    if args.universe == "full-market" and args.throttle is not None:
        logger.warning(
            "--throttle is deprecated: the data worker owns provider pacing and quotas"
        )

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
        exchanges=tuple(
            value.strip().upper()
            for value in args.exchanges.split(",")
            if value.strip()
        ),
        universe_snapshot_id=args.universe_snapshot_id,
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

    if summary.scope:
        logger.info("History scope: %s", summary.scope)
    for job in summary.jobs:
        logger.info("History job: %s", job)
    if summary.error:
        logger.error("Market sync failed: %s", summary.error)
    if summary.status == "queued":
        logger.info(
            "History remains pending; run the existing data worker and repeat this request to resume/check completion"
        )
        sys.exit(2)
    if summary.status in {"failed", "partial"} or summary.failed_targets > 0:
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
