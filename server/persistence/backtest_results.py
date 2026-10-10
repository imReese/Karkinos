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


def resolve_etf_backtest_record(
    database_path: str | Path,
    *,
    bound_result_id: int | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Resolve the target ETF rotation backtest row and its forward paper book summary."""
    import json
    from contextlib import closing
    from datetime import timezone
    from decimal import Decimal

    from server.persistence.connection import connect_sqlite
    from server.persistence.research_paper_books import ResearchPaperBooksRepository

    resolved_path = Path(database_path)
    if not resolved_path.exists():
        return None, None

    try:
        with closing(connect_sqlite(resolved_path, readonly=True)) as conn:
            conn.row_factory = sqlite3.Row
            has_bt_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='backtest_results'"
            ).fetchone()
            if not has_bt_table:
                return None, None

            target_row = None
            if bound_result_id is not None:
                row = conn.execute(
                    "SELECT * FROM backtest_results WHERE id = ?",
                    (bound_result_id,),
                ).fetchone()
                if row:
                    target_row = dict(row)
            else:
                rows = conn.execute(
                    "SELECT * FROM backtest_results ORDER BY id DESC"
                ).fetchall()
                for r in rows:
                    try:
                        cfg = json.loads(r["config_json"]) if r["config_json"] else {}
                        if cfg.get("strategy") == "etf_rotation":
                            target_row = dict(r)
                            break
                    except Exception:
                        continue

            if target_row is None:
                return None, None

            result_id = int(target_row["id"])
            paper_book_summary: dict[str, Any] | None = None

            has_obs = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_observations'"
            ).fetchone()
            has_paper = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_paper_books'"
            ).fetchone()

            if has_obs and has_paper:
                obs_row = conn.execute(
                    "SELECT id FROM research_observations WHERE source_backtest_result_id = ? ORDER BY id DESC LIMIT 1",
                    (result_id,),
                ).fetchone()
                if obs_row:
                    obs_id = obs_row["id"]
                    paper_repo = ResearchPaperBooksRepository(
                        resolved_path,
                        clock=lambda: datetime.now(timezone.utc),
                    )
                    paper_detail = paper_repo.get(obs_id)
                    if paper_detail:
                        perf = paper_detail.get("performance", {})
                        health = paper_detail.get("health", {})
                        net_ret = Decimal(str(perf.get("net_return", "0")))
                        mdd_paper = Decimal(str(perf.get("max_drawdown", "0")))
                        paper_book_summary = {
                            "book_id": paper_detail["id"],
                            "observation_id": obs_id,
                            "settled_sessions": perf.get("settled_sessions", 0),
                            "equity": perf.get(
                                "equity",
                                str(paper_detail.get("initial_cash", "0")),
                            ),
                            "net_return": perf.get("net_return", "0"),
                            "net_return_pct": round(float(net_ret) * 100, 2),
                            "max_drawdown": perf.get("max_drawdown", "0"),
                            "max_drawdown_pct": round(float(mdd_paper) * 100, 2),
                            "fees_paid": perf.get("fees_paid", "0"),
                            "slippage_cost": perf.get("slippage_cost", "0"),
                            "health_status": health.get("status", "not_configured"),
                            "through_session": perf.get("through_session"),
                            "evaluation_start": paper_detail.get("evaluation_start"),
                        }

            return target_row, paper_book_summary
    except Exception:
        return None, None
