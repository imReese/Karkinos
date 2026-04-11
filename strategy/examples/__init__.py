"""策略示例 — 导入即注册。"""

from strategy.examples.bollinger import BollingerStrategy
from strategy.examples.dual_ma import DualMAStrategy
from strategy.examples.monthly_rebalance import MonthlyRebalanceStrategy
from strategy.examples.rsi import RSIStrategy

__all__ = [
    "DualMAStrategy",
    "MonthlyRebalanceStrategy",
    "RSIStrategy",
    "BollingerStrategy",
]
