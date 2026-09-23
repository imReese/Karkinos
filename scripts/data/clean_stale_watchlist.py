#!/usr/bin/env python3
"""Inspect and clean stale or liquidated assets from persistent watchlist_assets."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.bootstrap import load_runtime_config
from server.config import ServerConfig
from server.db import AppDatabase
from server.runtime_paths import resolve_data_dir
from server.services.market_views.health_inputs import rebuild_portfolio_from_ledger
from server.services.position_presence import is_economically_zero_quantity


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect and clean stale/liquidated assets from watchlist_assets table."
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Path to data directory containing app.db. Defaults to KARKINOS_DATA_DIR or resolve_data_dir().",
    )
    parser.add_argument(
        "--config-path",
        default=None,
        help="Path to config.json. Defaults to KARKINOS_CONFIG_PATH.",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help="Specific symbols to remove from watchlist_assets.",
    )
    parser.add_argument(
        "--prune-zero-holdings",
        action="store_true",
        help="Remove all watchlist assets that have zero holding quantity or no ledger position.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute deletion. Without this flag, script runs in dry-run mode.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    data_dir = (
        Path(args.data_dir).resolve()
        if args.data_dir
        else Path(os.getenv("KARKINOS_DATA_DIR") or resolve_data_dir()).resolve()
    )
    db_path = data_dir / "app.db"
    if not db_path.is_file():
        print(f"Error: database not found at {db_path}", file=sys.stderr)
        return 1

    print(f"Using database: {db_path}")
    db = AppDatabase(db_path)

    config_overrides = {}
    if args.config_path:
        config_overrides["config_path"] = args.config_path
    config = load_runtime_config(ServerConfig, **config_overrides)

    # Rebuild ledger positions to know exact current quantities
    rebuilt = rebuild_portfolio_from_ledger(config, db)
    positions = rebuilt.portfolio.positions

    watchlist_assets = db.list_watchlist_assets_sync()
    if not watchlist_assets:
        print("watchlist_assets is empty.")
        return 0

    print(f"\nFound {len(watchlist_assets)} assets in watchlist_assets:")
    print(
        f"{'Symbol':<10} {'Name':<18} {'Class':<8} {'Source':<18} {'Quantity':<12} {'Status'}"
    )
    print("-" * 75)

    candidates_to_prune: list[dict] = []
    for item in watchlist_assets:
        sym = item.get("symbol", "")
        name = item.get("display_name", "") or sym
        ac = item.get("asset_class", "")
        source = item.get("source", "")

        pos = positions.get(sym)
        qty = getattr(pos, "quantity", None) if pos is not None else None
        is_holding = pos is not None and not is_economically_zero_quantity(qty)

        if not is_holding:
            status = (
                "NO_HOLDING (qty=0)"
                if pos is not None
                else "NO_HOLDING (not in portfolio)"
            )
        else:
            status = f"HOLDING ({float(qty):.2f})"

        print(
            f"{sym:<10} {name:<18} {ac:<8} {source:<18} {str(qty) if qty is not None else 'None':<12} {status}"
        )

        if args.symbols and sym in args.symbols:
            candidates_to_prune.append(item)
        elif args.prune_zero_holdings and not is_holding:
            candidates_to_prune.append(item)

    if not args.symbols and not args.prune_zero_holdings:
        print(
            "\n[Dry-run] No filter specified (--symbols or --prune-zero-holdings). No actions planned."
        )
        print(
            "Tip: Use --prune-zero-holdings [--apply] or --symbols <SYM1> <SYM2> [--apply]"
        )
        return 0

    if not candidates_to_prune:
        print("\nNo matching assets found to prune.")
        return 0

    print(f"\nTarget assets to remove ({len(candidates_to_prune)}):")
    for item in candidates_to_prune:
        print(f"  - {item['symbol']} ({item.get('display_name', '')})")

    if not args.apply:
        print("\n[DRY RUN ONLY] Specify --apply to execute removal.")
        return 0

    print("\nExecuting removal...")
    deleted_count = 0
    for item in candidates_to_prune:
        sym = item["symbol"]
        ok = db.delete_watchlist_asset_sync(sym)
        if ok:
            print(f"  ✓ Deleted {sym}")
            deleted_count += 1
        else:
            print(f"  ✗ Failed to delete {sym}")

    print(f"\nDone. Successfully removed {deleted_count} assets from watchlist_assets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
