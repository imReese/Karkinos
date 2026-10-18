#!/usr/bin/env python3
"""Verify local market bars against a configured provider."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.types import AssetClass, BarFrequency, InstrumentType, Symbol
from data.manager import DataManager, build_sources
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
    parser.add_argument(
        "--start",
        required=True,
        help="Inclusive start date (YYYY-MM-DD) or ISO datetime.",
    )
    parser.add_argument(
        "--end",
        required=True,
        help="Inclusive end date (whole day, YYYY-MM-DD) or exact ISO datetime.",
    )
    parser.add_argument(
        "--asset-class",
        choices=[asset_class.value for asset_class in AssetClass],
        help="Provider grouping. Defaults to the instrument type, or stock.",
    )
    parser.add_argument(
        "--instrument-type",
        choices=[
            kind.value for kind in InstrumentType if kind is not InstrumentType.UNKNOWN
        ],
        help="Exact local cache identity; required when --asset-class is fund.",
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
        default=None,
        help="DataStore root path. Defaults to resolve_data_dir().",
    )
    parser.add_argument(
        "--tushare-token-env",
        default="TUSHARE_TOKEN",
        help="Environment variable name for a TuShare token when needed.",
    )
    parser.add_argument("--price-tolerance", type=float, default=0.01)
    parser.add_argument("--volume-tolerance", type=float, default=1.0)
    args = parser.parse_args(argv)
    asset_class = AssetClass(args.asset_class) if args.asset_class is not None else None
    if args.instrument_type is None:
        if asset_class is AssetClass.FUND:
            parser.error(
                "fund verification requires --instrument-type etf or open_end_fund"
            )
        instrument_type = InstrumentType.from_persisted(
            (asset_class or AssetClass.STOCK).value
        )
    else:
        instrument_type = InstrumentType.from_persisted(args.instrument_type)
    expected_asset_class = DataManager.get_instrument_by_type(
        Symbol(args.symbol), instrument_type
    ).asset_class
    if asset_class is not None and asset_class is not expected_asset_class:
        parser.error("--instrument-type conflicts with --asset-class")
    args.asset_class = expected_asset_class.value
    args.instrument_type = instrument_type
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    from server.runtime_paths import resolve_data_dir

    start = datetime.fromisoformat(args.start)
    try:
        end_date = date.fromisoformat(args.end)
    except ValueError:
        end = datetime.fromisoformat(args.end)
    else:
        end = datetime.combine(end_date, time.max)
    root = args.root or resolve_data_dir()
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
        DataStore(root),
        source,
        Symbol(args.symbol),
        start,
        end,
        BarFrequency(args.frequency),
        provider_name=args.provider,
        asset_class=AssetClass(args.asset_class),
        instrument_type=args.instrument_type,
        price_tolerance=args.price_tolerance,
        volume_tolerance=args.volume_tolerance,
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0 if report.status == "matched" else 1


if __name__ == "__main__":
    raise SystemExit(main())
