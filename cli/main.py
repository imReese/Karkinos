"""Compatibility wrapper for the backtest CLI.

Prefer `uv run python -m tools.run_backtest`. Use `./scripts/start_server.sh`
for the source Web service or the installed release's `karkinosctl`.
"""

from __future__ import annotations

from tools.run_backtest import main

if __name__ == "__main__":
    main()
