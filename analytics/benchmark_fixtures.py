"""Synthetic deterministic backtests for validation-matrix test journeys.

These rows are not persisted, PIT admission, or strategy/account promotion proof.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import pandas as pd

import strategy.builtins  # noqa: F401
from analytics.oos_validation import build_out_of_sample_validation
from backtest.engine import BacktestEngine, research_execution_config
from core.event_bus import EventBus
from core.types import AssetClass, BarFrequency, Symbol
from data.handler import DataHandler
from domain.instrument import Instrument, make_etf, make_stock
from strategy.registry import StrategyRegistry


@dataclass(frozen=True)
class BenchmarkFixtureSpec:
    strategy_id: str
    benchmark_role: str
    split_timestamp: datetime
    benchmark_return: Decimal
    instruments: dict[Symbol, Instrument]
    price_series: dict[Symbol, list[float]]
    strategy_kwargs: dict[str, Any]


def build_benchmark_fixture_backtest_rows() -> list[dict[str, str | int]]:
    """Run every built-in's synthetic OOS and after-cost fixture."""
    rows: list[dict[str, str | int]] = []
    for result_id, spec in enumerate(_benchmark_fixture_specs(), start=1):
        result = _run_fixture_backtest(spec)
        evidence_json = (
            result.evidence_bundle.to_json_dict()
            if result.evidence_bundle is not None
            else {}
        )
        oos_validation = build_out_of_sample_validation(
            strategy_id=spec.strategy_id,
            benchmark_role=spec.benchmark_role,
            result=result,
            split_timestamp=spec.split_timestamp,
            benchmark_return=spec.benchmark_return,
        ).to_json_dict()
        metrics_json = result.metrics.to_json_dict()
        metrics_json["evidence_bundle"] = evidence_json
        metrics_json["oos_validation"] = oos_validation
        metrics_json["execution_timing"] = result.execution_timing

        rows.append(
            {
                "id": result_id,
                "config_json": json.dumps(
                    {
                        "strategy": spec.strategy_id,
                        "fixture": "benchmark_validation",
                        "start_date": result.equity_curve[0][0].date().isoformat(),
                        "end_date": result.equity_curve[-1][0].date().isoformat(),
                        "oos_split_date": spec.split_timestamp.date().isoformat(),
                        "benchmark_return": float(spec.benchmark_return),
                    }
                ),
                "metrics_json": json.dumps(metrics_json, ensure_ascii=False),
                "cost_summary_json": json.dumps(
                    result.cost_summary.to_json_dict(), ensure_ascii=False
                ),
            }
        )
    return rows


def _run_fixture_backtest(spec: BenchmarkFixtureSpec):
    strategy = StrategyRegistry.create(
        spec.strategy_id,
        EventBus(),
        **spec.strategy_kwargs,
    )
    handlers = {
        symbol: DataHandler(
            _bars_dataframe(prices),
            symbol,
            frequency=BarFrequency.DAILY,
            asset_class=instrument.asset_class,
            instrument_type=instrument.instrument_type,
        )
        for symbol, instrument in spec.instruments.items()
        for prices in [spec.price_series[symbol]]
    }
    engine = BacktestEngine(
        strategy=strategy,
        instruments=spec.instruments,
        data_handlers=handlers,
        initial_cash=Decimal("100000"),
        execution_config=research_execution_config(),
        **(
            {
                "strict_event_errors": True,
                "session_completed": strategy.require_complete_session,
            }
            if spec.strategy_id == "risk_parity_macro"
            else {}
        ),
    )
    return engine.run()


def _bars_dataframe(prices: list[float]) -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-05", periods=len(prices))
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": prices,
            "high": [price * 1.01 for price in prices],
            "low": [price * 0.99 for price in prices],
            "close": prices,
            "volume": [1_000_000.0] * len(prices),
        }
    )


def _benchmark_fixture_specs() -> list[BenchmarkFixtureSpec]:
    equity_etf = Symbol("510300")
    bond_etf = Symbol("511010")
    gold_etf = Symbol("518880")
    a_share = Symbol("600519")

    return [
        BenchmarkFixtureSpec(
            strategy_id="risk_parity_macro",
            benchmark_role="bounded_macro_risk_budgeting",
            split_timestamp=datetime(2026, 1, 26),
            benchmark_return=Decimal("0"),
            instruments={
                equity_etf: make_etf(str(equity_etf), "合成权益ETF"),
                bond_etf: make_etf(str(bond_etf), "合成国债ETF"),
                gold_etf: make_etf(str(gold_etf), "合成黄金ETF"),
            },
            # Each leg has nonzero, distinct return variation. Both sides of
            # the split include post-warmup targets and strictly later fills.
            price_series={
                equity_etf: [
                    10 + 0.04 * i + 0.1 * (i % 3) + 0.5 * max(i - 14, 0)
                    for i in range(24)
                ],
                bond_etf: [100 + 0.02 * i + 0.03 * (i % 2) for i in range(24)],
                gold_etf: [20 + 0.03 * i + 0.05 * (i % 5) for i in range(24)],
            },
            strategy_kwargs={
                "lookback_period": 10,
                "rebalance_interval": 2,
                "trend_filter": False,
                "cash_proxy": str(bond_etf),
            },
        ),
        BenchmarkFixtureSpec(
            strategy_id="dual_ma",
            benchmark_role="etf_rotation_trend_following",
            split_timestamp=datetime(2026, 1, 14),
            benchmark_return=Decimal("0"),
            instruments={equity_etf: make_etf(str(equity_etf), "沪深300ETF")},
            price_series={
                equity_etf: [
                    10,
                    9.9,
                    9.8,
                    9.7,
                    9.6,
                    9.7,
                    9.8,
                    9.9,
                    10,
                    10.1,
                    10.2,
                    10.3,
                    10.4,
                    10.5,
                ]
            },
            strategy_kwargs={"short_period": 3, "long_period": 5},
        ),
        BenchmarkFixtureSpec(
            strategy_id="monthly_rebalance",
            benchmark_role="defensive_allocation",
            split_timestamp=datetime(2026, 1, 26),
            benchmark_return=Decimal("0"),
            instruments={
                equity_etf: make_etf(str(equity_etf), "沪深300ETF"),
                bond_etf: make_etf(str(bond_etf), "合成国债ETF"),
                gold_etf: make_etf(str(gold_etf), "合成黄金ETF"),
            },
            price_series={
                equity_etf: [
                    10,
                    10.2,
                    10.4,
                    10.1,
                    10.3,
                    10.5,
                    10.7,
                    10.4,
                    10.8,
                    11.0,
                    10.9,
                    11.2,
                    11.4,
                    11.1,
                    11.3,
                    11.5,
                    11.7,
                    11.6,
                    11.8,
                    12.0,
                    12.1,
                    11.9,
                ],
                bond_etf: [
                    100,
                    100.1,
                    100.2,
                    100.1,
                    100.3,
                    100.2,
                    100.4,
                    100.5,
                    100.4,
                    100.6,
                    100.5,
                    100.7,
                    100.8,
                    100.7,
                    100.9,
                    101.0,
                    100.9,
                    101.1,
                    101.2,
                    101.1,
                    101.3,
                    101.2,
                ],
                gold_etf: [
                    400,
                    402,
                    401,
                    405,
                    407,
                    406,
                    409,
                    412,
                    410,
                    414,
                    416,
                    415,
                    418,
                    420,
                    419,
                    422,
                    425,
                    424,
                    427,
                    430,
                    429,
                    431,
                ],
            },
            strategy_kwargs={
                "target_weights": {
                    equity_etf: 0.4,
                    bond_etf: 0.3,
                    gold_etf: 0.2,
                }
            },
        ),
        BenchmarkFixtureSpec(
            strategy_id="bollinger",
            benchmark_role="a_share_or_etf_mean_reversion",
            split_timestamp=datetime(2026, 1, 14),
            benchmark_return=Decimal("0"),
            instruments={a_share: make_stock(str(a_share), "贵州茅台示例")},
            price_series={
                a_share: [
                    10,
                    10,
                    10,
                    10,
                    10,
                    8,
                    7.8,
                    8,
                    9,
                    10,
                    11,
                    10,
                    9,
                    10,
                    11,
                ]
            },
            strategy_kwargs={"bb_period": 5, "num_std": 1.0},
        ),
        BenchmarkFixtureSpec(
            strategy_id="time_series_momentum",
            benchmark_role="time_series_momentum",
            split_timestamp=datetime(2026, 1, 14),
            benchmark_return=Decimal("0"),
            instruments={equity_etf: make_etf(str(equity_etf), "沪深300ETF")},
            price_series={
                equity_etf: [
                    10,
                    10.1,
                    10.2,
                    10.5,
                    10.8,
                    11.0,
                    11.2,
                    10.7,
                    10.2,
                    9.8,
                    10.0,
                    10.5,
                    11.0,
                    11.4,
                    11.8,
                ]
            },
            strategy_kwargs={
                "lookback_period": 3,
                "min_return": 0.0,
                "exit_return": 0.0,
                "target_weight": 0.8,
            },
        ),
        BenchmarkFixtureSpec(
            strategy_id="donchian_breakout",
            benchmark_role="channel_breakout_trend_following",
            split_timestamp=datetime(2026, 1, 14),
            benchmark_return=Decimal("0"),
            instruments={equity_etf: make_etf(str(equity_etf), "沪深300ETF")},
            price_series={
                equity_etf: [
                    10,
                    10.1,
                    10.2,
                    10.4,
                    10.8,
                    11.2,
                    11.5,
                    11.1,
                    10.6,
                    10.0,
                    10.3,
                    10.7,
                    11.0,
                    11.4,
                    11.7,
                ]
            },
            strategy_kwargs={
                "entry_window": 3,
                "exit_window": 2,
                "target_weight": 0.9,
            },
        ),
        BenchmarkFixtureSpec(
            strategy_id="volatility_target_trend",
            benchmark_role="volatility_target_trend_following",
            split_timestamp=datetime(2026, 1, 14),
            benchmark_return=Decimal("0"),
            instruments={equity_etf: make_etf(str(equity_etf), "沪深300ETF")},
            price_series={
                equity_etf: [
                    10,
                    10.8,
                    10.1,
                    11.2,
                    10.4,
                    11.6,
                    10.9,
                    12.2,
                    11.1,
                    10.0,
                    10.4,
                    11.0,
                    11.8,
                    12.4,
                    13.0,
                ]
            },
            strategy_kwargs={
                "lookback_period": 3,
                "volatility_window": 3,
                "target_annual_volatility": 0.20,
                "max_weight": 1.0,
                "min_momentum": 0.0,
                "rebalance_threshold": 0.01,
            },
        ),
        BenchmarkFixtureSpec(
            strategy_id="pairs_ratio_mean_reversion",
            benchmark_role="pair_relative_value_mean_reversion",
            split_timestamp=datetime(2026, 1, 14),
            benchmark_return=Decimal("0"),
            instruments={
                equity_etf: make_etf(str(equity_etf), "沪深300ETF"),
                a_share: make_stock(str(a_share), "贵州茅台示例"),
            },
            price_series={
                equity_etf: [
                    10,
                    10,
                    10,
                    8,
                    9.5,
                    10.2,
                    10.5,
                    11.5,
                    10.3,
                    10.0,
                    9.4,
                    9.9,
                    10.4,
                    10.8,
                    11.0,
                ],
                a_share: [
                    10,
                    10,
                    10,
                    10,
                    10,
                    10,
                    10,
                    10,
                    10,
                    10,
                    10,
                    10,
                    10,
                    10,
                    10,
                ],
            },
            strategy_kwargs={
                "symbol_a": str(equity_etf),
                "symbol_b": str(a_share),
                "lookback_period": 4,
                "entry_z": 1.2,
                "exit_z": 0.3,
                "pair_weight": 1.0,
                "neutral_weight": 0.5,
            },
        ),
        BenchmarkFixtureSpec(
            strategy_id="rsi",
            benchmark_role="rsi_mean_reversion",
            split_timestamp=datetime(2026, 1, 14),
            benchmark_return=Decimal("0"),
            instruments={equity_etf: make_etf(str(equity_etf), "合成权益ETF")},
            price_series={
                equity_etf: [
                    10,
                    9.8,
                    9.6,
                    9.4,
                    9.2,
                    9.4,
                    9.7,
                    10,
                    10.2,
                    10,
                    9.8,
                    9.6,
                    9.8,
                    10,
                    10.2,
                ]
            },
            strategy_kwargs={"rsi_period": 3, "oversold": 30, "overbought": 70},
        ),
        BenchmarkFixtureSpec(
            strategy_id="etf_rotation",
            benchmark_role="cross_sectional_etf_rotation",
            split_timestamp=datetime(2026, 1, 14),
            benchmark_return=Decimal("0"),
            instruments={
                equity_etf: make_etf(str(equity_etf), "合成权益ETF"),
                gold_etf: make_etf(str(gold_etf), "合成黄金ETF"),
                bond_etf: make_etf(str(bond_etf), "合成国债ETF"),
            },
            price_series={
                equity_etf: [
                    10,
                    10.1,
                    10.2,
                    10.3,
                    10.4,
                    10.5,
                    10.4,
                    10.3,
                    10.2,
                    10.1,
                    10,
                    9.9,
                    9.8,
                    9.7,
                    9.6,
                ],
                gold_etf: [
                    10,
                    9.9,
                    9.8,
                    9.7,
                    9.6,
                    9.5,
                    9.6,
                    9.7,
                    9.8,
                    9.9,
                    10,
                    10.1,
                    10.2,
                    10.3,
                    10.4,
                ],
                bond_etf: [100] * 15,
            },
            strategy_kwargs={
                "lookback_period": 2,
                "volatility_window": 2,
                "top_k": 1,
                "rebalance_interval": 1,
                "use_risk_adjusted": False,
                "cash_proxy": str(bond_etf),
            },
        ),
    ]
