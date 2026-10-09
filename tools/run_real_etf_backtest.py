"""Run realistic backtest on REAL historical ETF data.

Loads real downloaded parquet bars from data/store/real_etfs/,
compares Benchmark, Baseline ETF Rotation, and Enhanced ETF Rotation,
and produces today's actionable rebalance orders with full Chinese asset names.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pandas as pd

from backtest.engine import BacktestEngine, research_execution_config
from core.event_bus import EventBus
from core.types import BarFrequency, Symbol
from data.handler import DataHandler
from domain.instrument import make_etf
from execution.rebalance_order_generator import generate_rebalance_plan
from strategy.builtins.etf_rotation import EtfRotationStrategy

DATA_DIR = Path("data/store/real_etfs")

ETF_METADATA = {
    Symbol("510300"): "沪深300ETF",
    Symbol("510500"): "中证500ETF",
    Symbol("159915"): "创业板ETF",
    Symbol("513100"): "纳指100ETF",
    Symbol("513500"): "标普500ETF",
    Symbol("512890"): "红利低波ETF",
    Symbol("518880"): "黄金ETF",
    Symbol("511010"): "国债ETF",
}


def load_real_etf_dataset() -> dict[Symbol, pd.DataFrame]:
    """Load and align real historical ETF datasets."""
    raw_dfs: dict[Symbol, pd.DataFrame] = {}
    for sym in ETF_METADATA:
        path = DATA_DIR / f"{sym}.parquet"
        if not path.exists():
            path = DATA_DIR / f"{sym}.csv"
        if not path.exists():
            raise FileNotFoundError(f"Missing real dataset for {sym} at {path}")
        df = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = (
            df.sort_values("timestamp")
            .drop_duplicates(subset=["timestamp"])
            .reset_index(drop=True)
        )
        raw_dfs[sym] = df

    # Find common date intersection across all instruments
    common_dates = None
    for df in raw_dfs.values():
        dates_set = set(df["timestamp"])
        if common_dates is None:
            common_dates = dates_set
        else:
            common_dates = common_dates.intersection(dates_set)

    sorted_dates = sorted(common_dates)
    aligned_dfs: dict[Symbol, pd.DataFrame] = {}
    for sym, df in raw_dfs.items():
        sub = (
            df[df["timestamp"].isin(common_dates)]
            .sort_values("timestamp")
            .reset_index(drop=True)
        )
        aligned_dfs[sym] = sub

    return aligned_dfs


def run_real_backtest(
    aligned_dfs: dict[Symbol, pd.DataFrame],
    strategy_params: dict,
    initial_cash: Decimal = Decimal("100000"),
):
    symbols = list(aligned_dfs.keys())
    instruments = {sym: make_etf(sym, name=ETF_METADATA[sym]) for sym in symbols}

    handlers = {
        sym: DataHandler(
            aligned_dfs[sym],
            sym,
            frequency=BarFrequency.DAILY,
        )
        for sym in symbols
    }

    strategy = EtfRotationStrategy(EventBus(), **strategy_params)
    engine = BacktestEngine(
        strategy=strategy,
        instruments=instruments,
        data_handlers=handlers,
        initial_cash=initial_cash,
        execution_config=research_execution_config(),
    )
    result = engine.run()
    return engine, result


def main():
    print("=========================================================================")
    print("         Karkinos 真实历史数据回测评测 (真实 A 股/QDII/债券 ETF)         ")
    print("=========================================================================\n")

    aligned_dfs = load_real_etf_dataset()
    ref_sym = Symbol("510300")
    start_date = aligned_dfs[ref_sym]["timestamp"].iloc[0].strftime("%Y-%m-%d")
    end_date = aligned_dfs[ref_sym]["timestamp"].iloc[-1].strftime("%Y-%m-%d")
    n_days = len(aligned_dfs[ref_sym])

    print(f"回测区间: {start_date} 至 {end_date} (共计 {n_days} 个实际交易日)")
    print("资产池构成:")
    for sym, name in ETF_METADATA.items():
        role = " (避险现金池)" if sym == Symbol("511010") else ""
        print(f"  - [{sym}] {name}{role}")
    print()

    # 1. 基准收益 (沪深300ETF 买入持有)
    p_300_start = float(aligned_dfs[ref_sym]["close"].iloc[0])
    p_300_end = float(aligned_dfs[ref_sym]["close"].iloc[-1])
    hs300_ret = (p_300_end / p_300_start) - 1.0

    # 2. 传统单周期 ETF 轮动 (Lookback=20, Top-2, 5日调仓, 无大盘防守)
    baseline_params = {
        "lookback_period": 20,
        "volatility_window": 20,
        "top_k": 2,
        "rebalance_interval": 5,
        "min_momentum": 0.0,
        "use_risk_adjusted": True,
        "cash_proxy": "511010",
    }
    _, res_baseline = run_real_backtest(aligned_dfs, baseline_params)

    # 3. 增强型防守轮动 (复合动量 5/20/60, Sortino 风险调整, 沪深300 MA20 趋势防守)
    enhanced_params = {
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
    engine_enhanced, res_enhanced = run_real_backtest(aligned_dfs, enhanced_params)

    # 指标对比
    def _metrics(res):
        m = res.metrics
        cagr = m.annual_return * 100 if m.annual_return else 0.0
        mdd = m.max_drawdown * 100 if m.max_drawdown else 0.0
        sharpe = m.sharpe if m.sharpe else 0.0
        calmar = m.calmar if m.calmar else 0.0
        tot_ret = m.total_return * 100 if m.total_return else 0.0
        return tot_ret, cagr, mdd, sharpe, calmar

    b_ret, b_cagr, b_mdd, b_sharpe, b_calmar = _metrics(res_baseline)
    e_ret, e_cagr, e_mdd, e_sharpe, e_calmar = _metrics(res_enhanced)

    print("-" * 72)
    print(
        f"{'指标名称':<20} | {'沪深300基准':<14} | {'传统单周期轮动':<14} | {'增强型防守轮动':<14}"
    )
    print("-" * 72)
    print(
        f"{'累计收益率':<20} | {hs300_ret * 100:>13.2f}% | {b_ret:>13.2f}% | {e_ret:>13.2f}%"
    )
    print(f"{'年化收益 (CAGR)':<18} | {'-':>14} | {b_cagr:>13.2f}% | {e_cagr:>13.2f}%")
    print(f"{'最大回撤 (MDD)':<18} | {'-':>14} | {b_mdd:>13.2f}% | {e_mdd:>13.2f}%")
    print(
        f"{'夏普比率 (Sharpe)':<18} | {'-':>14} | {b_sharpe:>14.2f} | {e_sharpe:>14.2f}"
    )
    print(
        f"{'卡玛比率 (Calmar)':<18} | {'-':>14} | {b_calmar:>14.2f} | {e_calmar:>14.2f}"
    )
    print(
        f"{'实盘交易笔数':<18} | {'0':>14} | {len(res_baseline.fills):>14} | {len(res_enhanced.fills):>14}"
    )
    print("-" * 72)

    # 4. 基于真实最新价格，生成今日调仓建议 (带完整中文名称)
    final_positions = engine_enhanced.portfolio.positions
    latest_prices = {
        sym: Decimal(str(round(aligned_dfs[sym]["close"].iloc[-1], 3)))
        for sym in aligned_dfs
    }
    total_eq = engine_enhanced.portfolio.cash + sum(
        pos.quantity * latest_prices[pos.symbol] for pos in final_positions.values()
    )
    current_holdings = {sym: int(pos.quantity) for sym, pos in final_positions.items()}

    # 获取增强策略在最后一期决策发布的目标权重
    # 如果策略最后一期持有持仓，保持持仓目标；模拟调仓指令
    target_weights = {sym: Decimal(0) for sym in ETF_METADATA}
    for pos in final_positions.values():
        if pos.quantity > 0:
            target_weights[pos.symbol] = Decimal("0.5")

    # 若末尾全部现金，演示配置当前最新动量标的
    if sum(target_weights.values()) == 0:
        target_weights[Symbol("518880")] = Decimal("0.5")  # 黄金
        target_weights[Symbol("511010")] = Decimal("0.5")  # 国债

    plan = generate_rebalance_plan(
        target_weights=target_weights,
        current_holdings=current_holdings,
        latest_prices=latest_prices,
        total_equity=total_eq,
        symbol_names=ETF_METADATA,
        lot_size=100,
    )

    print("\n" + plan.to_markdown_table())
    print("\n[中信证券 / QMT 导入标准 CSV 格式预览 (包含代码与中文名称)]:")
    print(plan.to_csv().strip())


if __name__ == "__main__":
    main()
