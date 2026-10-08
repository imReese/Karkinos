"""Long-only research allocation from aligned daily bars and risk budgets."""

from __future__ import annotations

import math
from collections import deque
from datetime import date, datetime
from decimal import Decimal
from typing import Mapping

import numpy as np

from core.event_bus import EventBus
from core.events import MarketEvent, SignalEvent
from core.types import BarFrequency, Symbol
from strategy.base import Strategy
from strategy.registry import register_strategy
from strategy.risk_budget import project_box_constraints, risk_budget_weights


@register_strategy("risk_parity_macro")
class RiskParityMacroStrategy(Strategy):
    """按完整日截面估计风险预算，再投影到资本权重上下限的研究策略。

    趋势过滤把跌破均线的非 cash_proxy 资产风险预算乘以 0.2，再归一化；
    cash_proxy 是池中豁免过滤的普通资产，不产生现金或保证防守仓位。
    权重上下限优先于风险预算，投影后不保证等风险贡献；不使用杠杆。
    """

    def __init__(
        self,
        event_bus: EventBus,
        lookback_period: int = 60,
        rebalance_interval: int = 20,
        trend_filter: bool = True,
        trend_ma_period: int = 60,
        max_asset_weight: float = 0.60,
        min_asset_weight: float = 0.05,
        cash_proxy: str | None = "511010",
        risk_budgets: Mapping[str, float] | None = None,
        strategy_id: str = "risk_parity_macro",
    ) -> None:
        super().__init__(strategy_id, event_bus)
        for name, value, minimum in (
            ("lookback_period", lookback_period, 10),
            ("rebalance_interval", rebalance_interval, 1),
            ("trend_ma_period", trend_ma_period, 1),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"risk_parity_macro_{name}_invalid")
        if not isinstance(trend_filter, bool):
            raise ValueError("risk_parity_macro_trend_filter_invalid")
        for bound in (min_asset_weight, max_asset_weight):
            if (
                isinstance(bound, bool)
                or not isinstance(bound, (int, float))
                or not math.isfinite(bound)
            ):
                raise ValueError("risk_parity_macro_weight_bounds_invalid")
        if not 0 <= min_asset_weight <= max_asset_weight <= 1:
            raise ValueError("risk_parity_macro_weight_bounds_invalid")
        if cash_proxy is not None and (
            not isinstance(cash_proxy, str) or not cash_proxy.strip()
        ):
            raise ValueError("risk_parity_macro_cash_proxy_invalid")
        if risk_budgets is not None and (
            not isinstance(risk_budgets, Mapping)
            or not risk_budgets
            or any(
                not isinstance(symbol, str)
                or isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
                for symbol, value in risk_budgets.items()
            )
        ):
            raise ValueError("risk_parity_macro_risk_budgets_invalid")
        self.lookback_period = lookback_period
        self.rebalance_interval = rebalance_interval
        self.trend_filter = trend_filter
        self.trend_ma_period = trend_ma_period
        self.max_asset_weight = max_asset_weight
        self.min_asset_weight = min_asset_weight
        self.cash_proxy_symbol = Symbol(cash_proxy) if cash_proxy is not None else None
        self.custom_risk_budgets = (
            dict(risk_budgets) if risk_budgets is not None else None
        )
        self._required_bars = max(
            lookback_period + 1, trend_ma_period if trend_filter else 1
        )
        self._history: deque[list[Decimal]] = deque(maxlen=self._required_bars)
        self._symbols: list[Symbol] = []
        self._pending: dict[Symbol, Decimal] = {}
        self._session_timestamp: datetime | None = None
        self._completed_sessions = 0

    def on_init(self, symbols: list[Symbol]) -> None:
        if len(symbols) < 2 or len(set(symbols)) != len(symbols):
            raise ValueError("risk_parity_macro_universe_requires_at_least_two_symbols")
        if self.cash_proxy_symbol is not None and self.cash_proxy_symbol not in symbols:
            raise ValueError("risk_parity_macro_cash_proxy_input_missing")
        if self.custom_risk_budgets is not None and set(
            self.custom_risk_budgets
        ) != set(symbols):
            raise ValueError("risk_parity_macro_risk_budgets_universe_mismatch")
        project_box_constraints(
            np.full(len(symbols), 1 / len(symbols)),
            self.min_asset_weight,
            self.max_asset_weight,
        )
        self._symbols = sorted(symbols)
        self._pending.clear()
        self._history.clear()
        self._session_timestamp = None
        self._last_timestamp = None
        self._completed_sessions = 0

    def on_data(self, event: MarketEvent) -> None:
        if event.symbol not in self._symbols:
            return
        if event.frequency != BarFrequency.DAILY:
            raise ValueError("risk_parity_macro_daily_bars_required")
        price = float(event.close)
        if not math.isfinite(price) or price <= 0:
            raise ValueError(f"risk_parity_macro_price_invalid:{event.symbol}")
        timestamp = event.timestamp
        if self._session_timestamp is not None:
            if timestamp < self._session_timestamp:
                raise ValueError("risk_parity_macro_bars_out_of_order")
            if timestamp != self._session_timestamp:
                if timestamp.date() == self._session_timestamp.date():
                    raise ValueError("risk_parity_macro_session_timestamps_mismatch")
                if len(self._pending) != len(self._symbols):
                    raise ValueError("risk_parity_macro_incomplete_session")
                self._pending.clear()
        if event.symbol in self._pending:
            raise ValueError("risk_parity_macro_duplicate_session_bar")
        self._session_timestamp = timestamp
        self._last_timestamp = timestamp
        self._pending[event.symbol] = event.close
        if len(self._pending) == len(self._symbols):
            self._history.append([self._pending[symbol] for symbol in self._symbols])
            self._completed_sessions += 1
            if self._completed_sessions % self.rebalance_interval == 0:
                self._rebalance()

    def require_complete_session(self, session: date) -> None:
        """The backtest session callback also validates the final basket."""
        if (
            self._session_timestamp is None
            or self._session_timestamp.date() != session
            or len(self._pending) != len(self._symbols)
        ):
            raise ValueError("risk_parity_macro_incomplete_session")

    def _rebalance(self) -> None:
        if len(self._history) < self._required_bars:
            return
        prices = np.asarray(self._history, dtype=float)
        window = prices[-self.lookback_period - 1 :]
        returns = window[1:] / window[:-1] - 1
        covariance = np.cov(returns, rowvar=False, ddof=1)
        budget = np.array(
            [self.custom_risk_budgets[str(symbol)] for symbol in self._symbols]
            if self.custom_risk_budgets is not None
            else [1.0] * len(self._symbols),
            dtype=float,
        )
        if self.trend_filter:
            averages = prices[-self.trend_ma_period :].mean(axis=0)
            for index, symbol in enumerate(self._symbols):
                if (
                    symbol != self.cash_proxy_symbol
                    and prices[-1, index] < averages[index]
                ):
                    budget[index] *= 0.2
        weights = project_box_constraints(
            risk_budget_weights(covariance, budget),
            self.min_asset_weight,
            self.max_asset_weight,
        )
        # Serialize exact full-investment weights without pushing the small
        # floating residual through an already capped asset.
        targets = [Decimal(str(weight)) for weight in weights]
        lower, upper = (
            Decimal(str(self.min_asset_weight)),
            Decimal(str(self.max_asset_weight)),
        )
        remainder = Decimal(1) - sum(targets)
        for index, target in enumerate(targets):
            adjustment = (
                min(remainder, upper - target)
                if remainder >= 0
                else max(remainder, lower - target)
            )
            targets[index] += adjustment
            remainder -= adjustment
        if remainder:
            raise ValueError("risk_parity_macro_weight_rounding_infeasible")
        assert self._session_timestamp is not None
        for symbol, weight in zip(self._symbols, targets, strict=True):
            self.event_bus.publish(
                SignalEvent(
                    timestamp=self._session_timestamp,
                    strategy_id=self.strategy_id,
                    symbol=symbol,
                    target_weight=weight,
                    price=self._pending[symbol],
                )
            )
