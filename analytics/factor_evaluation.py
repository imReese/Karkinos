"""Cross-sectional quantitative factor evaluation engine.

Provides canonical metrics for predictive alpha factor validation:
- Information Coefficient (IC) & Rank IC (Spearman)
- IC Information Ratio (ICIR), t-stat, hit rate
- Quantile return distribution (Q1..Q5) & Long-Short spread
- Monotonicity score across quantiles
"""

from __future__ import annotations

import math
from typing import Literal

import numpy as np
import pandas as pd


def _normal_cdf(x: float) -> float:
    """Standard normal cumulative distribution function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def calculate_ic(
    factor_df: pd.DataFrame,
    forward_returns: pd.DataFrame,
    method: Literal["spearman", "pearson"] = "spearman",
) -> pd.Series:
    """计算因子的时序信息系数 (Information Coefficient) 序列。

    Args:
        factor_df: 行索引为日期，列为各标的的因子值。
        forward_returns: 行索引为日期，列为各标的的未来收益率。
        method: "spearman" (Rank IC, 默认) 或 "pearson" (普通 IC)。

    Returns:
        pd.Series: 每个日期的截面 IC 值，索引与输入对齐。
    """
    common_idx = factor_df.index.intersection(forward_returns.index)
    common_cols = factor_df.columns.intersection(forward_returns.columns)

    if len(common_idx) == 0 or len(common_cols) == 0:
        return pd.Series(dtype=float, index=common_idx)

    f_sub = factor_df.loc[common_idx, common_cols]
    r_sub = forward_returns.loc[common_idx, common_cols]

    ic_values = []
    for dt in common_idx:
        f_row = f_sub.loc[dt]
        r_row = r_sub.loc[dt]

        # 过滤有效标的 (去除 NaN 和 inf)
        valid_mask = (
            f_row.notna() & r_row.notna() & np.isfinite(f_row) & np.isfinite(r_row)
        )
        if valid_mask.sum() < 2:
            ic_values.append(np.nan)
            continue

        valid_f = f_row[valid_mask].astype(float)
        valid_r = r_row[valid_mask].astype(float)

        # 检查方差是否为 0
        if float(valid_f.std()) == 0.0 or float(valid_r.std()) == 0.0:
            ic_values.append(np.nan)
            continue

        if method == "spearman":
            rank_f = valid_f.rank()
            rank_r = valid_r.rank()
            corr = rank_f.corr(rank_r)
        else:
            corr = valid_f.corr(valid_r)

        ic_values.append(float(corr) if pd.notna(corr) else np.nan)

    return pd.Series(ic_values, index=common_idx, name=f"{method}_ic")


def calculate_rank_ic(
    factor_df: pd.DataFrame,
    forward_returns: pd.DataFrame,
) -> pd.Series:
    """计算因子的 Rank IC (Spearman 秩相关系数) 序列。"""
    return calculate_ic(factor_df, forward_returns, method="spearman")


def summarize_ic(ic_series: pd.Series) -> dict[str, float]:
    """计算 IC 序列的统计摘要。

    Returns:
        dict 包含:
        - sample_count: 有效期数
        - mean_ic: IC 均值
        - std_ic: IC 标准差
        - icir: IC 均值 / IC 标准差 (IC 信息比率)
        - annualized_icir: 年化 ICIR (ICIR * sqrt(252))
        - t_stat: 统计显著性 t 检验值
        - p_value: 双尾显著性 p 值 (正态/t近拟)
        - positive_ratio: IC 大于 0 的期数比例
    """
    clean_ic = ic_series.dropna()
    n = len(clean_ic)
    if n == 0:
        return {
            "sample_count": 0.0,
            "mean_ic": 0.0,
            "std_ic": 0.0,
            "icir": 0.0,
            "annualized_icir": 0.0,
            "t_stat": 0.0,
            "p_value": 1.0,
            "positive_ratio": 0.0,
        }

    mean_ic = float(clean_ic.mean())
    std_ic = float(clean_ic.std(ddof=1)) if n > 1 else 0.0
    positive_ratio = float((clean_ic > 0).mean())

    if std_ic > 0 and n > 1:
        icir = mean_ic / std_ic
        annualized_icir = icir * math.sqrt(252)
        se = std_ic / math.sqrt(n)
        t_stat = mean_ic / se if se > 0 else 0.0
        # 双尾 p 值
        p_val = 2.0 * (1.0 - _normal_cdf(abs(t_stat)))
    else:
        icir = 0.0
        annualized_icir = 0.0
        t_stat = 0.0
        p_val = 1.0

    return {
        "sample_count": float(n),
        "mean_ic": round(mean_ic, 4),
        "std_ic": round(std_ic, 4),
        "icir": round(icir, 4),
        "annualized_icir": round(annualized_icir, 4),
        "t_stat": round(t_stat, 4),
        "p_value": round(p_val, 4),
        "positive_ratio": round(positive_ratio, 4),
    }


def calculate_quantile_returns(
    factor_df: pd.DataFrame,
    forward_returns: pd.DataFrame,
    n_quantiles: int = 5,
) -> pd.DataFrame:
    """按截面因子值等分分层，计算各分位数组合的收益序列。

    Args:
        factor_df: 行=时间，列=标的的因子值。
        forward_returns: 行=时间，列=标的的未来一期收益率。
        n_quantiles: 分组层数，默认 5 组 (Q1=最低, Q5=最高)。

    Returns:
        DataFrame: 每列为对应分位数收益 (Q1..Qn)，以及 'long_short' (Qn - Q1)。
    """
    if n_quantiles < 2:
        raise ValueError("n_quantiles must be at least 2")

    common_idx = factor_df.index.intersection(forward_returns.index)
    common_cols = factor_df.columns.intersection(forward_returns.columns)

    if len(common_idx) == 0 or len(common_cols) == 0:
        cols = [f"Q{i + 1}" for i in range(n_quantiles)] + ["long_short"]
        return pd.DataFrame(columns=cols, index=common_idx, dtype=float)

    f_sub = factor_df.loc[common_idx, common_cols]
    r_sub = forward_returns.loc[common_idx, common_cols]

    quantile_records = []
    for dt in common_idx:
        f_row = f_sub.loc[dt]
        r_row = r_sub.loc[dt]

        valid_mask = (
            f_row.notna() & r_row.notna() & np.isfinite(f_row) & np.isfinite(r_row)
        )
        if valid_mask.sum() < n_quantiles:
            row_dict = {f"Q{i + 1}": np.nan for i in range(n_quantiles)}
            row_dict["long_short"] = np.nan
            quantile_records.append(row_dict)
            continue

        valid_f = f_row[valid_mask].astype(float)
        valid_r = r_row[valid_mask].astype(float)

        try:
            labels = list(range(n_quantiles))
            bins = pd.qcut(valid_f, q=n_quantiles, labels=labels, duplicates="drop")
            grouped_rets = valid_r.groupby(bins, observed=False).mean()
            row_dict = {}
            for i in range(n_quantiles):
                val = grouped_rets.get(i, np.nan)
                row_dict[f"Q{i + 1}"] = float(val) if pd.notna(val) else np.nan

            q_top = row_dict[f"Q{n_quantiles}"]
            q_bot = row_dict["Q1"]
            if pd.notna(q_top) and pd.notna(q_bot):
                row_dict["long_short"] = q_top - q_bot
            else:
                row_dict["long_short"] = np.nan
            quantile_records.append(row_dict)
        except Exception:
            row_dict = {f"Q{i + 1}": np.nan for i in range(n_quantiles)}
            row_dict["long_short"] = np.nan
            quantile_records.append(row_dict)

    res_df = pd.DataFrame(quantile_records, index=common_idx)
    return res_df


def summarize_quantile_spread(quantile_returns: pd.DataFrame) -> dict[str, float]:
    """汇总分层收益表现与单调性分析。

    Returns:
        dict 包含多空利差的年化收益率、夏普比率、最大回撤，以及单调性得分。
    """
    if "long_short" not in quantile_returns.columns or quantile_returns.empty:
        return {
            "annualized_spread_return": 0.0,
            "annualized_spread_volatility": 0.0,
            "spread_sharpe": 0.0,
            "spread_max_drawdown": 0.0,
            "monotonicity_score": 0.0,
        }

    ls = quantile_returns["long_short"].dropna()
    if len(ls) == 0:
        return {
            "annualized_spread_return": 0.0,
            "annualized_spread_volatility": 0.0,
            "spread_sharpe": 0.0,
            "spread_max_drawdown": 0.0,
            "monotonicity_score": 0.0,
        }

    ann_ret = float(ls.mean() * 252)
    ann_vol = float(ls.std(ddof=1) * math.sqrt(252)) if len(ls) > 1 else 0.0
    sharpe = float(ann_ret / ann_vol) if ann_vol > 0 else 0.0

    # 最大回撤
    cum = (1.0 + ls).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    max_dd = float(abs(dd.min())) if len(dd) > 0 and not dd.isna().all() else 0.0

    # 单调性得分: Q1 到 Qn 的均值序列与分组序号 [0, 1, ..., n-1] 的秩相关性
    q_cols = [
        c for c in quantile_returns.columns if c.startswith("Q") and c[1:].isdigit()
    ]
    q_cols.sort(key=lambda x: int(x[1:]))
    if len(q_cols) >= 2:
        q_means = pd.Series([float(quantile_returns[c].mean()) for c in q_cols])
        ranks = pd.Series(list(range(len(q_cols))))
        if q_means.dropna().nunique() > 1:
            mono_corr = float(q_means.rank().corr(ranks.rank()))
            mono_score = mono_corr if pd.notna(mono_corr) else 0.0
        else:
            mono_score = 0.0
    else:
        mono_score = 0.0

    return {
        "annualized_spread_return": round(ann_ret, 4),
        "annualized_spread_volatility": round(ann_vol, 4),
        "spread_sharpe": round(sharpe, 4),
        "spread_max_drawdown": round(max_dd, 4),
        "monotonicity_score": round(mono_score, 4),
    }
