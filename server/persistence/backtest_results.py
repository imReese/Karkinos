"""SQLite repository for persisted backtest results."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


class BacktestResultsRepository:
    """Own backtest result persistence without running backtests."""

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path)

    async def save(
        self,
        config_json: str,
        initial_cash: float,
        final_equity: float,
        total_return: float,
        sharpe: float,
        max_dd: float,
        equity_curve_json: str,
        annual_return: float = 0.0,
        sortino: float = 0.0,
        win_rate: float = 0.0,
        duration_days: int = 0,
        metrics_json: str = "{}",
        cost_summary_json: str = "{}",
    ) -> int:
        with sqlite3.connect(self._database_path) as conn:
            result_id = insert_backtest_result(
                conn,
                created_at=datetime.now().isoformat(),
                config_json=config_json,
                initial_cash=initial_cash,
                final_equity=final_equity,
                total_return=total_return,
                sharpe=sharpe,
                max_dd=max_dd,
                equity_curve_json=equity_curve_json,
                annual_return=annual_return,
                sortino=sortino,
                win_rate=win_rate,
                duration_days=duration_days,
                metrics_json=metrics_json,
                cost_summary_json=cost_summary_json,
            )
            conn.commit()
            return result_id

    async def list_results(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self._database_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""SELECT id, created_at, config_json, initial_cash,
                          final_equity, total_return, sharpe, max_drawdown,
                          equity_curve_json, metrics_json, cost_summary_json
                   FROM backtest_results ORDER BY id DESC""").fetchall()
            return [dict(row) for row in rows]

    async def get_result(self, result_id: int) -> dict[str, Any] | None:
        with sqlite3.connect(self._database_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM backtest_results WHERE id = ?", (result_id,)
            ).fetchone()
            return dict(row) if row else None


def insert_backtest_result(
    conn: sqlite3.Connection,
    *,
    created_at: str,
    config_json: str,
    initial_cash: float,
    final_equity: float,
    total_return: float,
    sharpe: float,
    max_dd: float,
    equity_curve_json: str,
    annual_return: float = 0.0,
    sortino: float = 0.0,
    win_rate: float = 0.0,
    duration_days: int = 0,
    metrics_json: str = "{}",
    cost_summary_json: str = "{}",
) -> int:
    """Insert one canonical backtest row on the caller-owned transaction."""

    cursor = conn.execute(
        """INSERT INTO backtest_results
           (created_at, config_json, initial_cash, final_equity, total_return,
            sharpe, sortino, max_drawdown, win_rate, duration_days,
            equity_curve_json, metrics_json, cost_summary_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            created_at,
            config_json,
            initial_cash,
            final_equity,
            total_return,
            sharpe,
            sortino,
            max_dd,
            win_rate,
            duration_days,
            equity_curve_json,
            metrics_json,
            cost_summary_json,
        ),
    )
    return int(cursor.lastrowid or 0)
