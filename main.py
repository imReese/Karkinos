"""Compatibility wrapper for the backtest CLI.

Prefer `uv run python -m tools.run_backtest`. The Web service entry point is
`uv run python -m server` or `./scripts/start_server.sh`.
"""

from __future__ import annotations

from tools.run_backtest import main


if __name__ == "__main__":
    main()
