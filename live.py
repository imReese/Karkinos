"""Compatibility wrapper for the standalone live monitor CLI.

Prefer `uv run python -m tools.live_monitor`. The Web service live path uses
`server.scheduler.TradingScheduler` via `uv run python -m server`.
"""

from __future__ import annotations

from tools.live_monitor import main


if __name__ == "__main__":
    main()
