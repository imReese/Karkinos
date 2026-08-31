"""Thin entry point for the default-read-only legacy fund repair CLI."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.legacy_fund_trade_duplicate_repair_cli import main

if __name__ == "__main__":
    raise SystemExit(main())
