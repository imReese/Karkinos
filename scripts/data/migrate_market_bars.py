#!/usr/bin/env python3
"""Restore receipt-verified legacy stock history to typed market storage."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data.market_bar_identity import migrate_legacy_market_bars_to_v2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.getenv("KARKINOS_DATA_DIR", "data/store"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-plan", help="Fingerprint from the dry-run report.")
    args = parser.parse_args(argv)
    if args.apply and not args.expected_plan:
        parser.error("--apply requires --expected-plan from a reviewed dry run")
    database = Path(args.root).expanduser().resolve() / "meta.db"
    backup: Path | None = None
    if args.apply:
        # SQLite's backup API includes committed WAL pages. Keep a standalone
        # snapshot outside Git before adding rows to the real market database.
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = database.parent / "backups" / f"market-bars-{stamp}.db"
        backup.parent.mkdir(parents=True, exist_ok=True)
        with closing(
            sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
        ) as source:
            with closing(sqlite3.connect(backup)) as target:
                source.backup(target)
                target.execute("PRAGMA journal_mode=DELETE")
    result = migrate_legacy_market_bars_to_v2(
        database,
        dry_run=not args.apply,
        expected_plan_fingerprint=args.expected_plan,
    )
    print(
        json.dumps(
            {**result, "backup_path": str(backup) if backup else None},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
