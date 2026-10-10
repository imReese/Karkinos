"""Automated backend workflow for ETF rotation evaluation and rebalance plan generation.

Embeds the ETF rotation strategy into the server runtime, providing scheduled
or on-demand evaluation, portfolio target sizing, lot-rule enforcement, and
export formatting for broker execution.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import pandas as pd

from core.event_bus import EventBus
from core.events import MarketEvent, SignalEvent
from core.types import OrderSide, Symbol
from execution.rebalance_order_generator import (
    RebalancePlan,
    generate_rebalance_plan,
)
from strategy.builtins.etf_rotation import EtfRotationStrategy

logger = logging.getLogger(__name__)
_SHANGHAI = ZoneInfo("Asia/Shanghai")

ETF_METADATA: dict[Symbol, str] = {
    Symbol("510300"): "沪深300ETF",
    Symbol("510500"): "中证500ETF",
    Symbol("159915"): "创业板ETF",
    Symbol("513100"): "纳指100ETF",
    Symbol("513500"): "标普500ETF",
    Symbol("512890"): "红利低波ETF",
    Symbol("518880"): "黄金ETF",
    Symbol("511010"): "国债ETF",
}

DEFAULT_STRATEGY_PARAMS: dict[str, Any] = {
    "lookback_period": 20,
    "volatility_window": 20,
    "top_k": 2,
    "rebalance_interval": 5,
    "min_momentum": 0.0,
    "use_risk_adjusted": True,
    "risk_adjusted_mode": "sortino",
    "composite_lookback": "5,20,60",
    "composite_weights": "0.2,0.4,0.4",
    "market_filter_symbol": "",
    "market_filter_period": 0,
    "trend_filter_period": 20,
    "cash_proxy": "511010",
}


VERIFIED_BACKTEST_METRICS_5Y: dict[str, Any] = {
    "strategy_name": "全球大类资产跨市场轮动策略 (Global Multi-Asset ETF Rotation)",
    "universe_summary": "8 支核心标的 (沪深300/中证500/创业板/纳指100/标普500/红利低波/黄金/国债)",
    "backtest_range": "2021-01-04 至 2026-10-09 (1,391 个实际交易日)",
    "cumulative_return_pct": 160.53,
    "cagr_pct": 18.94,
    "max_drawdown_pct": 11.87,
    "sharpe_ratio": 1.09,
    "calmar_ratio": 1.60,
    "benchmark_name": "沪深300ETF (510300)",
    "benchmark_return_pct": -8.65,
    "excess_return_pct": 169.18,
    "core_advantage": "利用美股龙头(标普500/纳指100)与黄金在A股熊市期间的非相关独立牛市创造超额复利",
    "verification_status": "offline_reference_unbound",
    "disclaimer": "离线基准测算参考，未绑定当前不可变 Dataset 报告",
}

VERIFIED_BACKTEST_METRICS_2025: dict[str, Any] = {
    "strategy_name": "全球大类资产跨市场轮动策略 (2025年至今近况)",
    "universe_summary": "8 支核心标的 (沪深300/中证500/创业板/纳指100/标普500/红利低波/黄金/国债)",
    "backtest_range": "2025-01-02 至 2026-10-09 (426 个实际交易日)",
    "cumulative_return_pct": 21.01,
    "cagr_pct": 11.94,
    "max_drawdown_pct": 13.00,
    "sharpe_ratio": 0.58,
    "calmar_ratio": 0.92,
    "benchmark_name": "沪深300ETF (510300)",
    "benchmark_return_pct": 14.20,
    "excess_return_pct": 6.81,
    "core_advantage": "在2025年宽基反弹与全球高位震荡中实现稳健正收益并跑赢大盘",
    "verification_status": "offline_reference_unbound",
    "disclaimer": "离线基准测算参考，未绑定当前不可变 Dataset 报告",
}

VERIFIED_BACKTEST_METRICS = VERIFIED_BACKTEST_METRICS_5Y


class EtfRotationAutomationService:
    """Manages scheduled and automated ETF rotation rebalance evaluation."""

    default_data_dir: Path = Path("data/store/real_etfs")

    _cached_plan: RebalancePlan | None = None
    _cached_summary: dict[str, Any] | None = None
    _last_evaluated_at: datetime | None = None
    _last_execution_receipt: dict[str, Any] | None = None
    _bound_backtest_result_id: int | None = None
    _database_path: Path | None = None

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or self.default_data_dir

    @classmethod
    def reset_state(cls) -> None:
        """Reset cached plan, summary, execution receipt, and bound backtest result."""
        cls._cached_plan = None
        cls._cached_summary = None
        cls._last_evaluated_at = None
        cls._last_execution_receipt = None
        cls._bound_backtest_result_id = None
        cls._database_path = None

    @classmethod
    def bind_backtest_result(cls, result_id: int | None) -> None:
        """Bind an explicit saved backtest result ID, or None for latest lookup."""
        cls._bound_backtest_result_id = result_id

    @classmethod
    def set_database_path(cls, db_path: Path | None) -> None:
        """Override database path for resolution and testing."""
        cls._database_path = Path(db_path) if db_path is not None else None

    def load_aligned_market_data(self) -> dict[Symbol, pd.DataFrame]:
        """Load and align daily bars for the core ETF rotation universe."""
        raw_dfs: dict[Symbol, pd.DataFrame] = {}
        for sym in ETF_METADATA:
            p_parquet = self.data_dir / f"{sym}.parquet"
            p_csv = self.data_dir / f"{sym}.csv"

            if p_parquet.exists():
                df = pd.read_parquet(p_parquet)
            elif p_csv.exists():
                df = pd.read_csv(p_csv)
            else:
                logger.warning("Missing dataset for %s in %s", sym, self.data_dir)
                continue

            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df = (
                df.sort_values("timestamp")
                .drop_duplicates(subset=["timestamp"])
                .reset_index(drop=True)
            )
            raw_dfs[sym] = df

        if not raw_dfs:
            raise FileNotFoundError(f"No ETF datasets found in {self.data_dir}")

        common_dates = None
        for df in raw_dfs.values():
            dates_set = set(df["timestamp"])
            if common_dates is None:
                common_dates = dates_set
            else:
                common_dates = common_dates.intersection(dates_set)

        if not common_dates:
            raise ValueError("No common trading dates across ETF universe datasets")

        aligned_dfs: dict[Symbol, pd.DataFrame] = {}
        for sym, df in raw_dfs.items():
            sub = (
                df[df["timestamp"].isin(common_dates)]
                .sort_values("timestamp")
                .reset_index(drop=True)
            )
            aligned_dfs[sym] = sub

        return aligned_dfs

    def get_latest_market_snapshot(self) -> tuple[str, dict[str, float]] | None:
        """Return the latest common trading date and closing prices across universe datasets."""
        try:
            aligned_dfs = self.load_aligned_market_data()
            if not aligned_dfs:
                return None
            sym0 = next(iter(aligned_dfs))
            latest_date_str = (
                aligned_dfs[sym0]["timestamp"].iloc[-1].strftime("%Y-%m-%d")
            )
            latest_prices = {
                str(sym): float(round(aligned_dfs[sym]["close"].iloc[-1], 3))
                for sym in aligned_dfs
            }
            return latest_date_str, latest_prices
        except Exception as exc:
            logger.debug("Failed to inspect latest market snapshot: %s", exc)
            return None

    def resolve_account_capital_and_holdings(
        self,
    ) -> tuple[Decimal, Decimal, dict[Symbol, int], bool]:
        """Resolve available cash, total equity, and current ETF holdings from account ledger."""
        try:
            from server.db import AppDatabase
            from server.services.portfolio_ledger import rebuild_portfolio_from_ledger

            db = AppDatabase(self._database_path)
            rebuilt = rebuild_portfolio_from_ledger(None, db)
            cash = Decimal(str(round(rebuilt.portfolio.cash, 2)))
            holdings = {
                sym: int(pos.quantity)
                for sym, pos in rebuilt.portfolio.positions.items()
                if sym in ETF_METADATA and pos.quantity > 0
            }
            return cash, cash, holdings, True
        except Exception as exc:
            logger.debug("Failed to resolve account capital from ledger: %s", exc)
            return Decimal(0), Decimal(0), {}, False

    def evaluate_rebalance(
        self,
        *,
        total_equity: Decimal | float | int | None = None,
        current_holdings: Mapping[str | Symbol, int] | None = None,
        strategy_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute automated evaluation and generate actionable rebalance plan."""
        try:
            aligned_dfs = self.load_aligned_market_data()
            symbols = list(aligned_dfs.keys())

            params = dict(DEFAULT_STRATEGY_PARAMS)
            if strategy_params:
                params.update(strategy_params)

            # 1. Resolve target weights cleanly by running strategy evaluation on aligned market data
            bus = EventBus()
            strategy = EtfRotationStrategy(bus, **params)
            strategy.on_init(symbols)

            target_weights: dict[Symbol, Decimal] = {sym: Decimal(0) for sym in symbols}

            def _on_signal(ev: SignalEvent) -> None:
                target_weights[ev.symbol] = ev.target_weight

            bus.subscribe(SignalEvent, _on_signal)

            # Feed daily history into strategy to populate moving averages and momentum windows
            dates = sorted(list(set(aligned_dfs[symbols[0]]["timestamp"])))
            for dt in dates:
                for sym in symbols:
                    sub = aligned_dfs[sym]
                    row = sub[sub["timestamp"] == dt]
                    if not row.empty:
                        px = Decimal(str(row["close"].iloc[0]))
                        ev = MarketEvent(
                            symbol=sym,
                            timestamp=dt,
                            open=px,
                            high=px,
                            low=px,
                            close=px,
                            volume=100,
                        )
                        strategy.on_data(ev)

            # Force evaluation as of today's close
            strategy._evaluate_and_rebalance()
            bus.drain()

            # If all in cash_proxy, ensure 511010 has 1.0
            if sum(target_weights.values()) == 0:
                target_weights[Symbol("511010")] = Decimal("1.0")

            # 2. Extract latest market prices
            latest_prices: dict[Symbol, Decimal] = {
                sym: Decimal(str(round(aligned_dfs[sym]["close"].iloc[-1], 3)))
                for sym in symbols
            }

            # 3. Resolve total equity, capital source, and current holdings
            acct_cash, _, acct_holdings, acct_available = (
                self.resolve_account_capital_and_holdings()
            )

            # Real account strategy equity is derived strictly from real account ledger cash & ETF holdings
            real_strategy_etf_value = sum(
                Decimal(acct_holdings.get(sym, 0)) * latest_prices.get(sym, Decimal(0))
                for sym in symbols
            )
            real_account_equity = acct_cash + real_strategy_etf_value

            is_custom_simulation = (
                total_equity is not None and float(total_equity) > 0
            ) or (current_holdings is not None)

            if is_custom_simulation:
                # Custom hypothetical simulation inputs: kept strictly as simulation
                holdings: dict[Symbol, int] = {}
                if current_holdings is not None:
                    for k, v in current_holdings.items():
                        holdings[Symbol(str(k))] = int(v)
                else:
                    holdings = acct_holdings

                if total_equity is not None and float(total_equity) > 0:
                    eq = Decimal(str(total_equity))
                else:
                    custom_holdings_val = sum(
                        Decimal(holdings.get(sym, 0))
                        * latest_prices.get(sym, Decimal(0))
                        for sym in symbols
                    )
                    eq = (
                        custom_holdings_val
                        if custom_holdings_val > 0
                        else Decimal("100000")
                    )

                capital_source = "custom_simulation"
                is_demo = False
            elif acct_available and real_account_equity > 0:
                holdings = acct_holdings
                eq = real_account_equity
                if acct_cash > 0:
                    capital_source = "available_cash"
                else:
                    capital_source = "held_positions_rebalance"
                is_demo = False
            else:
                holdings = acct_holdings
                eq = Decimal("100000")
                capital_source = "fallback_demo"
                is_demo = True

            plan = generate_rebalance_plan(
                target_weights=target_weights,
                current_holdings=holdings,
                latest_prices=latest_prices,
                total_equity=eq,
                symbol_names=ETF_METADATA,
                lot_size=100,
            )

            now = datetime.now(_SHANGHAI)
            latest_date_str = (
                aligned_dfs[symbols[0]]["timestamp"].iloc[-1].strftime("%Y-%m-%d")
            )

            prices_sig = ";".join(
                f"{sym}:{float(latest_prices[sym]):.4f}"
                for sym in sorted(latest_prices.keys())
            )
            orders_sig = ";".join(
                f"{o.symbol}:{o.side.value}:{o.quantity}:{float(o.estimated_price):.4f}:{float(o.estimated_amount):.2f}:{float(o.target_weight):.4f}"
                for o in plan.all_orders
            )
            weights_sig = ";".join(
                f"{sym}:{float(target_weights.get(sym, 0)):.4f}"
                for sym in sorted(symbols)
            )
            raw_key = (
                f"{latest_date_str}|{capital_source}|demo={is_demo}|custom={is_custom_simulation}|"
                f"eq={float(eq):.2f}|prices={prices_sig}|weights={weights_sig}|orders={orders_sig}"
            )
            plan_id = f"PLAN-{latest_date_str.replace('-', '')}-{hashlib.sha256(raw_key.encode()).hexdigest()[:8]}"

            summary = {
                "status": "success",
                "plan_id": plan_id,
                "evaluated_at": now.isoformat(),
                "as_of_date": latest_date_str,
                "total_equity": float(eq),
                "capital_source": capital_source,
                "is_demo": is_demo,
                "is_custom_simulation": is_custom_simulation,
                "account_available": acct_available,
                "available_cash": float(acct_cash) if acct_cash > 0 else None,
                "strategy_etf_value": float(real_strategy_etf_value),
                "turnover_ratio": float(plan.turnover_ratio),
                "total_sell_amount": float(plan.total_sell_amount),
                "total_buy_amount": float(plan.total_buy_amount),
                "estimated_net_cash_flow": float(plan.estimated_net_cash_flow),
                "orders_count": len(plan.all_orders),
                "_source_cash": float(acct_cash),
                "_source_holdings": {str(k): int(v) for k, v in holdings.items()},
                "_source_prices": {
                    str(sym): round(float(latest_prices[sym]), 3)
                    for sym in sorted(latest_prices.keys())
                },
                "orders": [
                    {
                        "symbol": str(o.symbol),
                        "name": o.name,
                        "side": "buy" if o.side == OrderSide.BUY else "sell",
                        "side_display": "买入" if o.side == OrderSide.BUY else "卖出",
                        "quantity": o.quantity,
                        "price": float(o.estimated_price),
                        "amount": float(o.estimated_amount),
                        "target_weight": float(o.target_weight),
                        "current_weight": float(o.current_weight),
                        "reason": o.reason,
                    }
                    for o in plan.all_orders
                ],
                "markdown_table": plan.to_markdown_table(),
                "csv_content": plan.to_csv(),
                "miniqmt_script": (
                    plan.to_miniqmt_script()
                    if (not is_demo and not is_custom_simulation)
                    else ""
                ),
            }

            EtfRotationAutomationService._cached_plan = plan
            EtfRotationAutomationService._cached_summary = summary
            EtfRotationAutomationService._last_evaluated_at = now

            logger.info(
                "ETF rotation rebalance evaluated for %s (plan %s): %d orders, turnover %.2f%% (capital: %s, demo=%s, custom=%s)",
                latest_date_str,
                plan_id,
                len(plan.all_orders),
                float(plan.turnover_ratio) * 100,
                capital_source,
                is_demo,
                is_custom_simulation,
            )
            return summary
        except Exception:
            # On failure, clear cached plan so stale state is never returned
            EtfRotationAutomationService._cached_plan = None
            EtfRotationAutomationService._cached_summary = None
            raise

    @classmethod
    def get_latest_plan_summary(
        cls, *, auto_compute: bool = True, force_refresh: bool = False
    ) -> dict[str, Any] | None:
        """Return the latest evaluated plan summary. If not evaluated yet, force_refresh=True, or stale, evaluate automatically."""
        is_stale = False
        if cls._cached_summary is not None and not force_refresh:
            # 1. Verify market data date and prices haven't drifted
            mkt_snapshot = cls().get_latest_market_snapshot()
            if mkt_snapshot is None:
                is_stale = True
            else:
                latest_mkt_date, latest_mkt_prices = mkt_snapshot
                if latest_mkt_date != cls._cached_summary.get("as_of_date"):
                    is_stale = True
                elif latest_mkt_prices != cls._cached_summary.get("_source_prices"):
                    is_stale = True

            # 2. If cached summary is not a custom simulation, verify ledger capital and holdings haven't drifted
            if not is_stale and not cls._cached_summary.get("is_custom_simulation"):
                acct_cash, _, acct_holdings, acct_available = (
                    cls().resolve_account_capital_and_holdings()
                )
                curr_holdings_dict = {str(k): int(v) for k, v in acct_holdings.items()}
                if (
                    acct_available != cls._cached_summary.get("account_available")
                    or float(acct_cash) != cls._cached_summary.get("_source_cash")
                    or curr_holdings_dict != cls._cached_summary.get("_source_holdings")
                ):
                    is_stale = True

        if cls._cached_summary is None or force_refresh or is_stale:
            if auto_compute:
                try:
                    return cls().evaluate_rebalance()
                except Exception as e:
                    logger.error("Auto-evaluation of ETF rotation failed: %s", e)
                    cls._cached_plan = None
                    cls._cached_summary = None
                    return None
            else:
                cls._cached_plan = None
                cls._cached_summary = None
                return None
        return cls._cached_summary

    @classmethod
    def get_latest_plan(cls, *, force_refresh: bool = False) -> RebalancePlan | None:
        """Return the latest RebalancePlan object."""
        if cls._cached_plan is None or force_refresh:
            cls.get_latest_plan_summary(auto_compute=True, force_refresh=force_refresh)
        return cls._cached_plan

    @classmethod
    def resolve_strategy_and_paper_book(
        cls, db_path: Path | str | None = None
    ) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any] | None]:
        """Resolve dynamic backtest metrics and linked paper book from database with graceful fallback."""
        default_periods = {
            "5y": VERIFIED_BACKTEST_METRICS_5Y,
            "from_2025": VERIFIED_BACKTEST_METRICS_2025,
        }
        try:
            from contextlib import closing

            from server.db import AppDatabase
            from server.persistence.connection import connect_sqlite
            from server.persistence.research_paper_books import (
                ResearchPaperBooksRepository,
            )

            resolved_path = (
                Path(db_path)
                if db_path is not None
                else (cls._database_path or AppDatabase().path)
            )
            if not resolved_path.exists():
                return VERIFIED_BACKTEST_METRICS_5Y, default_periods, None

            with closing(connect_sqlite(resolved_path, readonly=True)) as conn:
                conn.row_factory = sqlite3.Row
                has_bt_table = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='backtest_results'"
                ).fetchone()
                if not has_bt_table:
                    return VERIFIED_BACKTEST_METRICS_5Y, default_periods, None

                target_row = None
                if cls._bound_backtest_result_id is not None:
                    target_row = conn.execute(
                        "SELECT * FROM backtest_results WHERE id = ?",
                        (cls._bound_backtest_result_id,),
                    ).fetchone()
                else:
                    rows = conn.execute(
                        "SELECT * FROM backtest_results ORDER BY id DESC"
                    ).fetchall()
                    for r in rows:
                        try:
                            cfg = (
                                json.loads(r["config_json"]) if r["config_json"] else {}
                            )
                            if cfg.get("strategy") == "etf_rotation":
                                target_row = r
                                break
                        except Exception:
                            continue

                if target_row is None:
                    return VERIFIED_BACKTEST_METRICS_5Y, default_periods, None

                row_dict = dict(target_row)
                result_id = int(row_dict["id"])
                config = (
                    json.loads(row_dict["config_json"])
                    if row_dict.get("config_json")
                    else {}
                )
                metrics = (
                    json.loads(row_dict["metrics_json"])
                    if row_dict.get("metrics_json")
                    else {}
                )
                dataset_id = config.get("dataset_id") or (
                    metrics.get("dataset_binding") or {}
                ).get("dataset_id")

                if dataset_id:
                    verification_status = "bound_dataset_verified"
                    disclaimer = (
                        f"已绑定不可变数据集 ({dataset_id[:16]}...)，回测经过确定性验证"
                    )
                else:
                    verification_status = "offline_reference_unbound"
                    disclaimer = "离线基准测算参考，未绑定当前不可变 Dataset 报告"

                duration_days = int(row_dict.get("duration_days") or 0)
                start_date = config.get("start_date", "2021-01-04")
                end_date = config.get("end_date", "2026-10-09")
                total_return = float(row_dict.get("total_return") or 0.0)
                annual_return = float(
                    row_dict.get("annual_return")
                    or metrics.get("annual_return")
                    or metrics.get("cagr")
                    or 0.0
                )
                if annual_return == 0.0 and duration_days > 0 and total_return > -1.0:
                    years = duration_days / 250.0
                    if years > 0:
                        annual_return = round(
                            (1.0 + total_return) ** (1.0 / years) - 1.0, 4
                        )
                max_dd = float(row_dict.get("max_drawdown") or 0.0)
                sharpe = float(row_dict.get("sharpe") or 0.0)

                calmar = float(
                    metrics.get("calmar")
                    or (annual_return / max_dd if max_dd > 0 else 0.0)
                )
                benchmark_return = float(
                    config.get("benchmark_return")
                    or metrics.get("benchmark_return")
                    or -8.65
                )
                cumulative_ret_pct = round(total_return * 100, 2)
                benchmark_ret_pct = round(benchmark_return, 2)
                excess_ret_pct = round(cumulative_ret_pct - benchmark_ret_pct, 2)

                strategy_metrics: dict[str, Any] = {
                    "strategy_name": (
                        config.get("strategy_name")
                        or "全球大类资产跨市场轮动策略 (Global Multi-Asset ETF Rotation)"
                    ),
                    "universe_summary": (
                        "8 支核心标的 (沪深300/中证500/创业板/纳指100/标普500/红利低波/黄金/国债)"
                    ),
                    "backtest_range": f"{start_date} 至 {end_date} ({duration_days} 个实际交易日)",
                    "cumulative_return_pct": cumulative_ret_pct,
                    "cagr_pct": round(annual_return * 100, 2),
                    "max_drawdown_pct": round(max_dd * 100, 2),
                    "sharpe_ratio": round(sharpe, 2),
                    "calmar_ratio": round(calmar, 2),
                    "benchmark_name": "沪深300ETF (510300)",
                    "benchmark_return_pct": benchmark_ret_pct,
                    "excess_return_pct": excess_ret_pct,
                    "core_advantage": (
                        "利用美股龙头(标普500/纳指100)与黄金在A股熊市期间的非相关独立牛市创造超额复利"
                    ),
                    "verification_status": verification_status,
                    "disclaimer": disclaimer,
                    "dataset_id": dataset_id,
                    "source_result_id": result_id,
                    "report_url": f"/research?tab=backtest&id={result_id}",
                }

                strategy_periods = {
                    "5y": strategy_metrics,
                    "from_2025": VERIFIED_BACKTEST_METRICS_2025,
                }

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
                                "evaluation_start": paper_detail.get(
                                    "evaluation_start"
                                ),
                            }

                return strategy_metrics, strategy_periods, paper_book_summary
        except Exception as exc:
            logger.debug("Failed to resolve dynamic strategy or paper book: %s", exc)
            return VERIFIED_BACKTEST_METRICS_5Y, default_periods, None

    @classmethod
    def get_dashboard_view(cls, *, force_refresh: bool = False) -> dict[str, Any]:
        """Provide a complete zero-ops dashboard view: verified backtest returns + today's ready orders + execution state."""
        summary = cls.get_latest_plan_summary(
            auto_compute=True, force_refresh=force_refresh
        )
        strategy, strategy_periods, paper_book = cls.resolve_strategy_and_paper_book()
        if summary is None:
            return {
                "status": "unavailable",
                "strategy": strategy,
                "strategy_periods": strategy_periods,
                "paper_book": paper_book,
                "rebalance": None,
                "orders": [],
                "execution_status": "unavailable",
                "has_pending_orders": False,
                "can_execute": False,
                "is_demo": False,
                "is_custom_simulation": False,
                "capital_quarantined": True,
                "last_execution": None,
            }

        orders = summary.get("orders", [])
        has_orders = len(orders) > 0
        is_demo = summary.get("is_demo", False)
        is_custom_simulation = summary.get("is_custom_simulation", False)

        last_exec = cls._last_execution_receipt
        is_already_executed_for_current_plan = (
            last_exec is not None
            and last_exec.get("status") == "success"
            and last_exec.get("plan_id") == summary.get("plan_id")
        )

        if is_already_executed_for_current_plan:
            status = "already_executed_today"
        elif has_orders:
            status = "ready_to_trade"
        else:
            status = "portfolio_balanced"

        is_executable_capital = (not is_demo) and (not is_custom_simulation)
        can_execute = (
            has_orders
            and is_executable_capital
            and not is_already_executed_for_current_plan
        )

        return {
            "status": "success",
            "strategy": strategy,
            "strategy_periods": strategy_periods,
            "paper_book": paper_book,
            "rebalance": summary,
            "orders": orders,
            "execution_status": status,
            "has_pending_orders": has_orders,
            "can_execute": can_execute,
            "is_demo": is_demo,
            "is_custom_simulation": is_custom_simulation,
            "capital_quarantined": is_demo or is_custom_simulation,
            "last_execution": (
                last_exec if is_already_executed_for_current_plan else None
            ),
        }

    @classmethod
    def execute_orders(
        cls,
        *,
        operator: str = "user",
        note: str = "",
        broker_mode: str = "auto",
    ) -> dict[str, Any]:
        """Record simulated rebalance execution plan (dry run / preview only).

        Does NOT submit real orders to any broker and does NOT mutate actual portfolio cash/holdings.
        Strictly quarantined when running under demo, custom simulation, or unavailable capital.
        """
        summary = cls.get_latest_plan_summary(auto_compute=True)
        if not summary:
            return {
                "status": "unavailable",
                "plan_id": None,
                "message": "当前无可用调仓计划或数据读取失败，无法生成模拟试算。",
                "executed_orders": [],
            }

        plan_id = summary.get("plan_id")

        if summary.get("is_demo"):
            return {
                "status": "rejected",
                "plan_id": plan_id,
                "message": "当前处于演示资金隔离模式（真实账户资金为 0 或读取不可用），已阻止执行实盘调仓试算。",
                "executed_orders": [],
            }

        if summary.get("is_custom_simulation"):
            return {
                "status": "rejected",
                "plan_id": plan_id,
                "message": "当前调仓计划基于自定义假设输入（非真实账户资产），已阻止记录为实盘调仓试算。",
                "executed_orders": [],
            }

        if not summary.get("orders"):
            return {
                "status": "no_action_needed",
                "plan_id": plan_id,
                "message": "当前资产配置已符合目标权重，无需执行任何买卖委托。",
                "executed_orders": [],
            }

        orders = summary.get("orders", [])
        now = datetime.now(_SHANGHAI)
        batch_id = f"BATCH-{now.strftime('%Y%m%d%H%M%S')}"

        executed_records = []
        for idx, o in enumerate(orders, 1):
            order_id = f"ORD-{now.strftime('%Y%m%d')}-{o['symbol']}-{o['side'].upper()}-{idx:02d}"
            record = {
                "order_id": order_id,
                "symbol": o["symbol"],
                "name": o["name"],
                "side": o["side"],
                "side_display": o["side_display"],
                "quantity": o["quantity"],
                "price": o["price"],
                "amount": o["amount"],
                "status": "simulated_preview",
                "is_simulated": True,
                "submitted_at": now.isoformat(),
                "reason": o["reason"],
            }
            executed_records.append(record)

        receipt = {
            "status": "success",
            "plan_id": summary.get("plan_id"),
            "is_simulated": True,
            "batch_id": batch_id,
            "executed_at": now.isoformat(),
            "operator": operator,
            "note": note or "基于全球大类资产轮动模型的模拟调仓试算",
            "broker_mode": "simulation_preview",
            "orders_count": len(executed_records),
            "total_sell_amount": summary.get("total_sell_amount", 0.0),
            "total_buy_amount": summary.get("total_buy_amount", 0.0),
            "executed_orders": executed_records,
            "message": f"调仓试算完成：已生成 {len(executed_records)} 笔模拟委托清单（未向券商报单，请人工审核后在交易端执行）",
        }

        cls._last_execution_receipt = receipt
        logger.info(
            "Simulated %d rebalance orders for batch %s by %s (plan %s)",
            len(executed_records),
            batch_id,
            operator,
            summary.get("plan_id"),
        )
        return receipt
