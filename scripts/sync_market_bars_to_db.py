#!/usr/bin/env python3
"""Sync local historical market bar mirrors into SQLite."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.types import BarFrequency
from data.store import DataStore


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Import existing data/store/bars parquet market data into "
            "data/store/meta.db.market_bars. This command does not fetch remote data."
        )
    )
    parser.add_argument(
        "--root",
        default=os.getenv("KARKINOS_DATA_DIR", "data/store"),
        help="DataStore root path. Defaults to KARKINOS_DATA_DIR or ./data/store.",
    )
    parser.add_argument(
        "--frequency",
        choices=[frequency.value for frequency in BarFrequency],
        help="Only sync one bar frequency, for example 1d.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    frequency = BarFrequency(args.frequency) if args.frequency else None
    summary = DataStore(args.root).sync_parquet_bars_to_database(frequency)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
