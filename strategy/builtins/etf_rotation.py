"""Cross-sectional ETF rotation strategy with momentum, trend filters, and defensive hedging."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date
from decimal import ROUND_DOWN, Decimal

from core.event_bus import EventBus
from core.events import MarketEvent
from core.types import Symbol
from strategy.base import Strategy
from strategy.registry import register_strategy


@register_strategy("etf_rotation")
class EtfRotationStrategy(Strategy):
    """多标的截面动量与 ETF 轮动策略。

    定期对股票池内各资产计算动量（或夏普/风险调整后动量），
    结合均线趋势过滤与绝对动量阈值，选取表现最优的 Top-K 标的进行等权配置。
    当市场整体走弱、无合格标的（或合格标的不足 Top-K）时，
    自动将闲置仓位切换至避险资产（如国债 ETF）或保留现金。
    """

    def __init__(
        self,
        event_bus: EventBus,
        lookback_period: int = 20,
        volatility_window: int = 20,
        top_k: int = 2,
        rebalance_interval: int = 5,
        min_momentum: float = 0.0,
        trend_filter_period: int = 0,
        use_risk_adjusted: bool = True,
        cash_proxy: str | None = "511010",
        composite_lookback: str = "",
        composite_weights: str = "",
        market_filter_symbol: str = "",
        market_filter_period: int = 0,
        risk_adjusted_mode: str = "volatility",
        strategy_id: str = "etf_rotation",
    ) -> None:
        super().__init__(strategy_id, event_bus)
        for name, value, minimum in (
            ("lookback_period", lookback_period, 1),
            ("volatility_window", volatility_window, 2),
            ("top_k", top_k, 1),
            ("rebalance_interval", rebalance_interval, 1),
            ("trend_filter_period", trend_filter_period, 0),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"etf_rotation_{name}_invalid")
        if not math.isfinite(min_momentum):
            raise ValueError("etf_rotation_min_momentum_invalid")
        if not isinstance(composite_lookback, str):
            raise ValueError("etf_rotation_composite_lookback_invalid")
        if not isinstance(composite_weights, str):
            raise ValueError("etf_rotation_composite_weights_invalid")
        if not isinstance(market_filter_symbol, str):
            raise ValueError("etf_rotation_market_filter_symbol_invalid")
        if (
            isinstance(market_filter_period, bool)
            or not isinstance(market_filter_period, int)
            or market_filter_period < 0
        ):
            raise ValueError("etf_rotation_market_filter_period_invalid")
        if risk_adjusted_mode not in ("volatility", "sharpe", "sortino", "none"):
            raise ValueError("etf_rotation_risk_adjusted_mode_invalid")

        self.lookback_period = lookback_period
        self.volatility_window = volatility_window
        self.top_k = top_k
        self.rebalance_interval = rebalance_interval
        self.min_momentum = min_momentum
        self.trend_filter_period = trend_filter_period
        self.use_risk_adjusted = use_risk_adjusted
        self.cash_proxy_symbol = Symbol(cash_proxy) if cash_proxy else None
        self.composite_lookback = composite_lookback
        self.composite_weights = composite_weights
        self.market_filter_symbol = (
            Symbol(market_filter_symbol.strip())
            if market_filter_symbol.strip()
            else None
        )
        self.market_filter_period = market_filter_period
        self.risk_adjusted_mode = risk_adjusted_mode

        self._parsed_windows: list[int] = []
        self._parsed_weights: list[float] = []
        if composite_lookback.strip():
            parts = [p.strip() for p in composite_lookback.split(",") if p.strip()]
            try:
                self._parsed_windows = [int(p) for p in parts]
            except ValueError:
                raise ValueError("etf_rotation_composite_lookback_invalid")
            if not self._parsed_windows or any(w <= 0 for w in self._parsed_windows):
                raise ValueError("etf_rotation_composite_lookback_invalid")

            if composite_weights.strip():
                w_parts = [p.strip() for p in composite_weights.split(",") if p.strip()]
                try:
                    raw_w = [float(p) for p in w_parts]
                except ValueError:
                    raise ValueError("etf_rotation_composite_weights_invalid")
                if (
                    len(raw_w) != len(self._parsed_windows)
                    or any(w < 0 for w in raw_w)
                    or sum(raw_w) <= 0
                ):
                    raise ValueError("etf_rotation_composite_weights_invalid")
                total_w = sum(raw_w)
                self._parsed_weights = [w / total_w for w in raw_w]
            else:
                n = len(self._parsed_windows)
                self._parsed_weights = [1.0 / n] * n
        else:
            self._parsed_windows = [lookback_period]
            self._parsed_weights = [1.0]

        self._all_symbols: list[Symbol] = []
        self._prices: dict[Symbol, list[float]] = defaultdict(list)
        self._latest_prices: dict[Symbol, float] = {}
        self._symbols_seen_today: set[Symbol] = set()

        self._current_date: date | None = None
        self._session_day_count: int = 0

    def on_init(self, symbols: list[Symbol]) -> None:
        if not symbols or len(set(symbols)) != len(symbols):
            raise ValueError("etf_rotation_universe_invalid")
        if self.cash_proxy_symbol and self.cash_proxy_symbol not in symbols:
            raise ValueError(
                f"etf_rotation_cash_proxy_input_missing:{self.cash_proxy_symbol}"
            )
        if self.market_filter_symbol and self.market_filter_symbol not in symbols:
            raise ValueError(
                f"etf_rotation_market_filter_input_missing:{self.market_filter_symbol}"
            )
        self._all_symbols = sorted(symbols)
        self._prices.clear()
        self._latest_prices.clear()
        self._current_date = None
        self._session_day_count = 0
        for sym in self._all_symbols:
            self._prices[sym] = []
            self._latest_prices[sym] = 0.0
        self._symbols_seen_today = set()

    def on_data(self, event: MarketEvent) -> None:
        self._last_timestamp = event.timestamp
        sym = event.symbol
        if sym not in self._all_symbols:
            return
        price = float(event.close)
        if not math.isfinite(price) or price <= 0:
            raise ValueError(f"etf_rotation_price_invalid:{sym}")

        self._prices[sym].append(price)
        self._latest_prices[sym] = price

        event_date = event.timestamp.date()
        if self._current_date != event_date:
            self._current_date = event_date
            self._session_day_count += 1
            self._symbols_seen_today = set()

        self._symbols_seen_today.add(sym)

        # 当当日所有关注标的均已接收到行情时触发调仓评估
        if self._symbols_seen_today >= set(self._all_symbols):
            if self._session_day_count % self.rebalance_interval == 0:
                self._evaluate_and_rebalance()

    def _evaluate_and_rebalance(self) -> None:
        """执行截面排序并调整目标权重。"""
        # 候选标的为资产池中除现金替代标的外的所有标的
        candidates = [s for s in self._all_symbols if s != self.cash_proxy_symbol]
        if not candidates:
            return

        # 检查大盘防御过滤：若配置了 market_filter_symbol 且当前价格低于其均线，触发全局防守
        if self.market_filter_symbol and self.market_filter_period > 0:
            m_history = self._prices.get(self.market_filter_symbol, [])
            if len(m_history) >= self.market_filter_period + 1:
                m_ma = (
                    sum(m_history[-self.market_filter_period :])
                    / self.market_filter_period
                )
                m_curr = m_history[-1]
                if m_curr < m_ma:
                    self._apply_targets([])
                    return

        # 检查是否有足够的历史数据
        max_lookback = (
            max(self._parsed_windows) if self._parsed_windows else self.lookback_period
        )
        required_len = (
            max(
                max_lookback,
                self.volatility_window if self.use_risk_adjusted else 1,
                self.trend_filter_period,
                self.market_filter_period if self.market_filter_symbol else 0,
            )
            + 1
        )

        scores: list[tuple[Symbol, float]] = []
        for sym in candidates:
            history = self._prices.get(sym, [])
            if len(history) < required_len:
                continue

            current_price = history[-1]

            # 计算动量（支持单窗口或多周期复合加权）
            raw_momentum = 0.0
            valid_mom = True
            for win, w in zip(self._parsed_windows, self._parsed_weights):
                ref_price = history[-win - 1]
                if ref_price <= 0:
                    valid_mom = False
                    break
                raw_momentum += w * ((current_price / ref_price) - 1.0)
            if not valid_mom:
                continue

            # 绝对动量过滤：动量低于阈值则跳过
            if raw_momentum < self.min_momentum:
                continue

            # 均线趋势过滤：当前价格若低于长期均线则跳过
            if self.trend_filter_period > 0:
                ma = (
                    sum(history[-self.trend_filter_period :]) / self.trend_filter_period
                )
                if current_price < ma:
                    continue

            # 评分计算（支持波动率调整与 Sortino 下行风险惩罚）
            if (
                self.use_risk_adjusted
                and self.volatility_window > 1
                and self.risk_adjusted_mode != "none"
            ):
                window_slice = history[-self.volatility_window - 1 :]
                returns = [
                    window_slice[i] / window_slice[i - 1] - 1.0
                    for i in range(1, len(window_slice))
                    if window_slice[i - 1] > 0
                ]
                if self.risk_adjusted_mode == "sortino":
                    downside_returns = [r for r in returns if r < 0]
                    if downside_returns:
                        downside_var = sum(r**2 for r in downside_returns) / len(
                            returns
                        )
                        downside_vol = math.sqrt(downside_var) * math.sqrt(252)
                    else:
                        downside_vol = 0.0
                    score = raw_momentum / max(downside_vol, 0.03)
                else:
                    if len(returns) > 1:
                        mean_ret = sum(returns) / len(returns)
                        var = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
                        realized_vol = math.sqrt(var) * math.sqrt(252)
                    else:
                        realized_vol = 0.0
                    score = raw_momentum / max(realized_vol, 0.05)
            else:
                score = raw_momentum

            scores.append((sym, score))

        # 按得分从高到低排序
        scores.sort(key=lambda x: (-x[1], x[0]))
        selected_symbols = [s for s, _ in scores[: self.top_k]]
        self._apply_targets(selected_symbols)

    def _apply_targets(self, selected_symbols: list[Symbol]) -> None:
        """根据选出的标的清单计算并发布目标权重。"""

        next_targets = {s: Decimal(0) for s in self._all_symbols}
        precision = Decimal("0.0001")
        unit_weight = (Decimal(1) / self.top_k).quantize(precision, rounding=ROUND_DOWN)

        for sym in selected_symbols:
            next_targets[sym] = unit_weight

        # 未分配权重切换至避险资产 (cash_proxy)
        allocated_weight = (Decimal(len(selected_symbols)) / self.top_k).quantize(
            precision, rounding=ROUND_DOWN
        )
        # Assign the rounding remainder deterministically, without increasing
        # gross exposure above the exact selected-slot allocation.
        if selected_symbols:
            next_targets[selected_symbols[0]] += allocated_weight - sum(
                (next_targets[s] for s in selected_symbols), Decimal(0)
            )
        unallocated = Decimal(1) - allocated_weight

        if self.cash_proxy_symbol and self.cash_proxy_symbol in self._all_symbols:
            if unallocated > 0:
                next_targets[self.cash_proxy_symbol] = unallocated
            else:
                next_targets[self.cash_proxy_symbol] = Decimal(0)

        # A published target is intent, not a fill. Each scheduled review sends
        # fresh targets, and Portfolio sizes the differences from actual holdings.
        # This retries a blocked/partial buy after another symbol releases cash.
        for sym in self._all_symbols:
            target = next_targets[sym]
            px = self._latest_prices.get(sym)
            self.emit_signal(sym, target_weight=float(target), price=px)
