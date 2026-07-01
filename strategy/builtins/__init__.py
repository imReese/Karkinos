"""Built-in strategy implementations imported for registration."""

from strategy.builtins.bollinger import BollingerStrategy
from strategy.builtins.donchian_breakout import DonchianBreakoutStrategy
from strategy.builtins.dual_ma import DualMAStrategy
from strategy.builtins.monthly_rebalance import MonthlyRebalanceStrategy
from strategy.builtins.pairs_ratio_mean_reversion import (
    PairsRatioMeanReversionStrategy,
)
from strategy.builtins.rsi import RSIStrategy
from strategy.builtins.time_series_momentum import TimeSeriesMomentumStrategy
from strategy.builtins.volatility_target_trend import VolatilityTargetTrendStrategy

__all__ = [
    "DualMAStrategy",
    "MonthlyRebalanceStrategy",
    "RSIStrategy",
    "BollingerStrategy",
    "TimeSeriesMomentumStrategy",
    "DonchianBreakoutStrategy",
    "VolatilityTargetTrendStrategy",
    "PairsRatioMeanReversionStrategy",
]
