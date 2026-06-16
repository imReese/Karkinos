#!/usr/bin/env python3
"""Verify local market bars against a configured provider."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.types import AssetClass, BarFrequency, Symbol
from data.manager import build_sources
from data.market_data_reconciliation import reconcile_store_with_provider
from data.store import DataStore


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch provider bars for one symbol/range and compare them with "
            "local data/store/meta.db.market_bars. This command is read-only "
            "for market data and does not overwrite the local cache."
        )
    )
    parser.add_argument("--symbol", required=True, help="Symbol to verify.")
    parser.add_argument("--start", required=True, help="Start date, YYYY-MM-DD.")
    parser.add_argument("--end", required=True, help="End date, YYYY-MM-DD.")
    parser.add_argument(
        "--asset-class",
        default=AssetClass.STOCK.value,
        choices=[asset_class.value for asset_class in AssetClass],
    )
    parser.add_argument(
        "--frequency",
        default=BarFrequency.DAILY.value,
        choices=[frequency.value for frequency in BarFrequency],
    )
    parser.add_argument(
        "--provider",
        default=os.getenv("KARKINOS_DATA_SOURCE", "akshare"),
        help="Provider name registered by DataManager. Defaults to akshare.",
    )
    parser.add_argument(
        "--root",
        default=os.getenv("KARKINOS_DATA_DIR", "data/store"),
        help="DataStore root path. Defaults to KARKINOS_DATA_DIR or ./data/store.",
    )
    parser.add_argument(
        "--tushare-token-env",
        default="TUSHARE_TOKEN",
        help="Environment variable name for a TuShare token when needed.",
    )
    parser.add_argument("--price-tolerance", type=float, default=0.01)
    parser.add_argument("--volume-tolerance", type=float, default=1.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    sources = build_sources(
        data_source=args.provider,
        tushare_token=os.getenv(args.tushare_token_env, ""),
    )
    source = sources.get(args.provider)
    if source is None:
        available = ", ".join(sorted(sources))
        raise SystemExit(
            f"Provider '{args.provider}' is unavailable; available={available}"
        )

    report = reconcile_store_with_provider(
        DataStore(args.root),
        source,
        Symbol(args.symbol),
        datetime.fromisoformat(args.start),
        datetime.fromisoformat(args.end),
        BarFrequency(args.frequency),
        provider_name=args.provider,
        asset_class=AssetClass(args.asset_class),
        price_tolerance=args.price_tolerance,
        volume_tolerance=args.volume_tolerance,
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0 if report.status == "matched" else 1


if __name__ == "__main__":
    raise SystemExit(main())
