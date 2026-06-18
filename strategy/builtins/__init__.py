"""Built-in strategy implementations imported for registration."""

from strategy.builtins.bollinger import BollingerStrategy
from strategy.builtins.dual_ma import DualMAStrategy
from strategy.builtins.monthly_rebalance import MonthlyRebalanceStrategy
from strategy.builtins.rsi import RSIStrategy

__all__ = [
    "DualMAStrategy",
    "MonthlyRebalanceStrategy",
    "RSIStrategy",
    "BollingerStrategy",
]
